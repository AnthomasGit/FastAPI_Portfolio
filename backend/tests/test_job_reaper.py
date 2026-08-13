"""Recovering jobs left `running` by a hard stop.

`stop()` reverts what the worker claimed, but it reads the in-memory `_inflight`
set — SIGKILL, an OOM kill and `docker compose restart` all skip it. The rows
then sit in `running` forever: claim_jobs only selects `queued` and retry_failed
only selects `failed`, so nothing in the app can reach them. One such row (a
`plate_angles` job) was found stranded in the real database.
"""
import os
import uuid
from datetime import datetime

import pytest
import respx
from httpx import Response
from sqlalchemy import select

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from database import JobRecord
from services.comfyui_client import COMFY_API_URL
from services.job_worker import JobWorker, claim_jobs


async def _orphan(session_factory, **kw):
    """A row exactly as a hard-killed worker leaves it: running, never reverted."""
    async with session_factory() as db:
        job = JobRecord(kind=kw.pop("kind", "scene_image"), status="running",
                        started_at=datetime.utcnow(), attempts=kw.pop("attempts", 1),
                        payload={"prompt": "a cat"}, **kw)
        db.add(job)
        await db.commit()
        return job.job_id


async def _get(session_factory, job_id):
    async with session_factory() as db:
        return (await db.execute(
            select(JobRecord).where(JobRecord.job_id == job_id)
        )).scalars().first()


def _queue(*prompt_ids):
    """A ComfyUI /queue body listing the given prompts as running."""
    return {"queue_running": [[0, pid, {}, {}, []] for pid in prompt_ids],
            "queue_pending": []}


@pytest.mark.asyncio
async def test_never_submitted_orphan_is_requeued(session_factory):
    job_id = await _orphan(session_factory)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)

    assert await worker.reap_orphans() == 1

    job = await _get(session_factory, job_id)
    assert job.status == "queued"
    assert job.started_at is None


@pytest.mark.asyncio
async def test_requeued_orphan_becomes_claimable_again(session_factory):
    """The point of the exercise: claim_jobs only ever selects `queued`, so an
    orphan is unreachable until it is put back."""
    job_id = await _orphan(session_factory)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)

    async with session_factory() as db:
        assert await claim_jobs(db, 5) == []          # unreachable while running

    await worker.reap_orphans()

    async with session_factory() as db:
        claimed = await claim_jobs(db, 5)
    assert [j.job_id for j in claimed] == [job_id]


@pytest.mark.asyncio
async def test_orphan_still_rendering_in_comfyui_is_left_alone(session_factory):
    """ComfyUI outlives the API container. Requeuing a prompt it is still
    working on would submit the same graph twice and burn a GPU slot."""
    prompt_id = str(uuid.uuid4())
    job_id = await _orphan(session_factory, prompt_id=prompt_id)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/queue").mock(
            return_value=Response(200, json=_queue(prompt_id)))
        assert await worker.reap_orphans() == 0

    job = await _get(session_factory, job_id)
    assert job.status == "running"
    assert job.prompt_id == prompt_id


@pytest.mark.asyncio
async def test_orphan_whose_prompt_is_gone_is_requeued(session_factory):
    """Submitted, but ComfyUI no longer has it — the render was lost with the
    crash, so it has to run again. The stale prompt_id is cleared so the retry
    does not poll a dead prompt."""
    prompt_id = str(uuid.uuid4())
    job_id = await _orphan(session_factory, prompt_id=prompt_id)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/queue").mock(
            return_value=Response(200, json=_queue("someone-else")))
        assert await worker.reap_orphans() == 1

    job = await _get(session_factory, job_id)
    assert job.status == "queued"
    assert job.prompt_id is None


@pytest.mark.asyncio
async def test_attempts_survive_so_a_crash_loop_still_terminates(session_factory):
    """A job that kills the worker every time must exhaust max_attempts rather
    than being resurrected with a clean slate forever."""
    job_id = await _orphan(session_factory, attempts=2, max_attempts=3)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)

    await worker.reap_orphans()

    job = await _get(session_factory, job_id)
    assert job.attempts == 2          # NOT reset


@pytest.mark.asyncio
async def test_reap_unblocks_the_dependents_an_orphan_stranded(session_factory):
    """The blast radius that matters now: claim_jobs requires a dependency to be
    *completed*, not merely terminal, so one orphaned base plate leaves every
    cell of its sheet queued forever."""
    plate_id = await _orphan(session_factory, kind="base_plate")
    async with session_factory() as db:
        cell = JobRecord(kind="character_sheet", status="queued",
                         depends_on_job_id=plate_id, payload={})
        db.add(cell)
        await db.commit()
        cell_id = cell.job_id

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    await worker.reap_orphans()

    # The plate runs first; the cell stays blocked until it completes.
    async with session_factory() as db:
        claimed = await claim_jobs(db, 5)
    assert [j.job_id for j in claimed] == [plate_id]

    async with session_factory() as db:
        job = (await db.execute(
            select(JobRecord).where(JobRecord.job_id == plate_id)
        )).scalars().first()
        job.status = "completed"
        await db.commit()

    async with session_factory() as db:
        claimed = await claim_jobs(db, 5)
    assert [j.job_id for j in claimed] == [cell_id]


@pytest.mark.asyncio
async def test_terminal_jobs_are_untouched(session_factory):
    ids = {}
    for status in ("completed", "failed", "cancelled", "queued"):
        async with session_factory() as db:
            job = JobRecord(kind="scene_image", status=status, payload={})
            db.add(job)
            await db.commit()
            ids[status] = job.job_id

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    assert await worker.reap_orphans() == 0

    for status, job_id in ids.items():
        assert (await _get(session_factory, job_id)).status == status


@pytest.mark.asyncio
async def test_start_reaps_before_the_loop_runs(session_factory):
    """Recovery happens on boot, not when a human notices.

    max_inflight=0 keeps the loop from claiming anything, so what is observed
    afterwards is purely the reap.
    """
    job_id = await _orphan(session_factory, attempts=1)
    worker = JobWorker(session_factory=session_factory, max_inflight=0)

    await worker.start()
    await worker.stop()

    job = await _get(session_factory, job_id)
    assert job.status == "queued"
    assert job.started_at is None
    assert job.attempts == 1      # reaped, not re-claimed

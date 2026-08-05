"""KAN-22 — job dependencies and deferred scheduling."""
import os
import json
import uuid
from datetime import datetime, timedelta

import pytest
import respx
from httpx import Response

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from database import JobRecord
from services.comfyui_client import COMFY_API_URL
from services.job_worker import JobWorker, claim_jobs


def _history(prompt_id, status_str="success"):
    return {prompt_id: {"status": {"status_str": status_str}, "outputs": {}}}


def _submitted_prompt(call):
    workflow = json.loads(call.request.content)["prompt"]
    return workflow["57:27"]["inputs"]["text"]


async def _add(session_factory, **kw):
    async with session_factory() as db:
        job = JobRecord(kind=kw.pop("kind", "scene_image"),
                        payload=kw.pop("payload", {"prompt": "x"}),
                        **kw)
        db.add(job)
        await db.commit()
        return job.job_id


@pytest.mark.asyncio
async def test_dependent_waits_then_resolves_parent_output(session_factory):
    a_id = await _add(session_factory, payload={"prompt": "parent"})
    # B references A's output filename via the $from_parent placeholder.
    b_id = await _add(
        session_factory,
        payload={"prompt": {"$from_parent": "image_url"}},
        depends_on_job_id=a_id,
    )

    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=0)

    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            side_effect=[
                Response(200, json={"prompt_id": "pa"}),
                Response(200, json={"prompt_id": "pb"}),
            ]
        )
        respx.get(f"{COMFY_API_URL}/history/pa").mock(
            return_value=Response(200, json=_history("pa"))
        )
        respx.get(f"{COMFY_API_URL}/history/pb").mock(
            return_value=Response(200, json=_history("pb"))
        )

        # Tick 1: only A is claimable (B blocked on incomplete dependency).
        processed = await worker.tick()
        assert processed == 1
        assert submit_route.call_count == 1
        async with session_factory() as db:
            a = await db.get(JobRecord, a_id)
            b = await db.get(JobRecord, b_id)
            assert a.status == "completed"
            assert b.status == "queued"  # still waiting
        a_output = a.image_url
        assert a_output

        # Tick 2: A is complete, B runs and its prompt resolved A's output.
        processed = await worker.tick()
        assert processed == 1

    assert _submitted_prompt(submit_route.calls[1]) == a_output
    async with session_factory() as db:
        assert (await db.get(JobRecord, b_id)).status == "completed"


@pytest.mark.asyncio
async def test_upstream_failure_cancels_dependents(session_factory):
    a_id = await _add(session_factory, max_attempts=1)
    b_id = await _add(session_factory, depends_on_job_id=a_id)
    c_id = await _add(session_factory, depends_on_job_id=b_id)  # transitive

    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=0)

    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(500, text="boom")
        )
        await worker.tick()  # A fails terminally

    async with session_factory() as db:
        a = await db.get(JobRecord, a_id)
        b = await db.get(JobRecord, b_id)
        c = await db.get(JobRecord, c_id)
    assert a.status == "failed"
    assert b.status == "cancelled"
    assert "upstream" in (b.error or "")
    assert c.status == "cancelled"  # cascaded
    # B was never submitted (only A's failing submit happened).
    assert submit_route.call_count == 1


@pytest.mark.asyncio
async def test_scheduled_after_skipped_until_clock_passes(session_factory):
    future = datetime.utcnow() + timedelta(hours=1)
    job_id = await _add(session_factory, scheduled_after=future)

    async with session_factory() as db:
        # Before its scheduled time: not claimable.
        claimed = await claim_jobs(db, 1, now=datetime.utcnow())
        assert claimed == []

    async with session_factory() as db:
        # After the clock passes it (injected, no sleep): claimable.
        claimed = await claim_jobs(db, 1, now=future + timedelta(seconds=1))
        assert [j.job_id for j in claimed] == [job_id]

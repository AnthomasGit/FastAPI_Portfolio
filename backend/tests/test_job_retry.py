"""KAN-21 — retry with backoff, idempotent output paths."""
import os
import json
import uuid

import pytest
import respx
from httpx import Response

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from database import JobRecord
from services.comfyui_client import COMFY_API_URL
from services.job_worker import JobWorker


def _history(prompt_id, status_str):
    return {prompt_id: {"status": {"status_str": status_str}, "outputs": {}}}


def _submitted_prefix(call):
    """filename_prefix injected into node 9 of a submitted scene_image workflow."""
    workflow = json.loads(call.request.content)["prompt"]
    return workflow["9"]["inputs"]["filename_prefix"]


async def _enqueue(session_factory, **kw):
    async with session_factory() as db:
        job = JobRecord(kind="scene_image", payload={"prompt": "a cat"}, **kw)
        db.add(job)
        await db.commit()
        return job.job_id


@pytest.mark.asyncio
async def test_retry_then_success_uses_second_attempt_prefix(session_factory):
    job_id = await _enqueue(session_factory)  # max_attempts default 3
    # zero backoff so the requeued job is immediately claimable
    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=0)

    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            side_effect=[
                Response(200, json={"prompt_id": "p1"}),
                Response(200, json={"prompt_id": "p2"}),
            ]
        )
        respx.get(f"{COMFY_API_URL}/history/p1").mock(
            return_value=Response(200, json=_history("p1", "error"))
        )
        respx.get(f"{COMFY_API_URL}/history/p2").mock(
            return_value=Response(200, json=_history("p2", "success"))
        )

        # Attempt 1: submit ok, history error -> requeued.
        await worker.tick()
        async with session_factory() as db:
            job = await db.get(JobRecord, job_id)
            assert job.status == "queued"
            assert job.attempts == 1
            first_image_url = job.image_url  # attempt-1 prefix was written

        # Attempt 2: fresh prefix, submit ok, history success -> completed.
        await worker.tick()

    prefix1 = _submitted_prefix(submit_route.calls[0])
    prefix2 = _submitted_prefix(submit_route.calls[1])
    assert prefix1 != prefix2  # each attempt regenerated its output prefix

    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
    assert job.status == "completed"
    assert job.attempts == 2
    # The winning row points at the SECOND attempt's output, not the first.
    assert job.image_url == f"{prefix2}_00001_.png"
    assert job.image_url != first_image_url


@pytest.mark.asyncio
async def test_exhausts_max_attempts_then_failed_and_not_reclaimed(session_factory):
    job_id = await _enqueue(session_factory, max_attempts=2)
    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=0)

    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(return_value=Response(500, text="boom"))

        await worker.tick()  # attempt 1 -> requeue
        async with session_factory() as db:
            assert (await db.get(JobRecord, job_id)).status == "queued"

        await worker.tick()  # attempt 2 -> failed (2 == max_attempts)
        async with session_factory() as db:
            job = await db.get(JobRecord, job_id)
            assert job.status == "failed"
            assert job.error
            assert job.attempts == 2
            assert job.finished_at is not None

        # A further tick must not reclaim a failed job.
        processed = await worker.tick()
        assert processed == 0
        async with session_factory() as db:
            assert (await db.get(JobRecord, job_id)).status == "failed"


@pytest.mark.asyncio
async def test_backoff_sets_future_scheduled_after(session_factory):
    from datetime import datetime
    job_id = await _enqueue(session_factory)
    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=30)

    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(return_value=Response(500, text="boom"))
        await worker.tick()

    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
    assert job.status == "queued"
    assert job.scheduled_after is not None
    assert job.scheduled_after > datetime.utcnow()

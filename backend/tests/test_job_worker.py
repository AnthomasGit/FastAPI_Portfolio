"""KAN-20 — background worker loop.

Key property under test: a job reaches `completed` via the worker with NO client
polling call anywhere. ComfyUI is mocked with respx.
"""
import os
import uuid

import pytest
import respx
from httpx import Response
from sqlalchemy import select

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from database import JobRecord
from services.comfyui_client import COMFY_API_URL
from services.job_worker import JobWorker, claim_jobs


def _history_completed(prompt_id):
    return {
        prompt_id: {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"9": {"images": [{"filename": f"{prompt_id}_00001_.png"}]}},
        }
    }


async def _enqueue(session_factory, **kw):
    async with session_factory() as db:
        job = JobRecord(kind=kw.pop("kind", "scene_image"),
                        payload=kw.pop("payload", {"prompt": "a cat"}),
                        **kw)
        db.add(job)
        await db.commit()
        return job.job_id


@pytest.mark.asyncio
async def test_worker_completes_job_without_client_polling(session_factory):
    prompt_id = str(uuid.uuid4())
    job_id = await _enqueue(session_factory)

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=_history_completed(prompt_id))
        )
        processed = await worker.tick()

    assert processed == 1
    assert submit_route.called

    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
        assert job.status == "completed"
        assert job.prompt_id == prompt_id
        assert job.image_url is not None
        assert job.finished_at is not None


@pytest.mark.asyncio
async def test_max_inflight_limits_submits_per_tick(session_factory):
    # Two queued jobs, MAX_INFLIGHT=1 -> only one submitted in a single tick.
    await _enqueue(session_factory)
    await _enqueue(session_factory)

    prompt_id = str(uuid.uuid4())
    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=_history_completed(prompt_id))
        )
        processed = await worker.tick()

    assert processed == 1
    assert submit_route.call_count == 1

    async with session_factory() as db:
        statuses = sorted(
            j.status for j in (await db.execute(select(JobRecord))).scalars().all()
        )
    assert statuses == ["completed", "queued"]


@pytest.mark.asyncio
async def test_claim_respects_priority_and_scheduling(session_factory):
    from datetime import datetime, timedelta
    # low priority, high priority, and one scheduled in the future
    await _enqueue(session_factory, priority=0)
    hi = await _enqueue(session_factory, priority=10)
    await _enqueue(session_factory, scheduled_after=datetime.utcnow() + timedelta(hours=1))

    async with session_factory() as db:
        claimed = await claim_jobs(db, 1)
    assert len(claimed) == 1
    assert claimed[0].job_id == hi  # highest priority, and future job skipped


@pytest.mark.asyncio
async def test_failed_submit_marks_job_failed(session_factory):
    # max_attempts=1 -> a single submit failure is terminal (retry logic is
    # exercised separately in test_job_retry.py).
    job_id = await _enqueue(session_factory, max_attempts=1)
    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(return_value=Response(500, text="boom"))
        await worker.tick()

    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
        assert job.status == "failed"
        assert job.error


@pytest.mark.asyncio
async def test_stop_requeues_inflight_job(session_factory):
    # Simulate a job the worker claimed but never finished.
    job_id = await _enqueue(session_factory)
    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
        job.status = "running"
        await db.commit()

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    worker._inflight.add(job_id)
    await worker.stop()

    async with session_factory() as db:
        job = await db.get(JobRecord, job_id)
        assert job.status == "queued"
        assert job.started_at is None

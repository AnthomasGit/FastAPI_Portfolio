"""KAN-27 — batch progress / cancel / retry-failed."""
import uuid

import pytest
from sqlalchemy import select

from database import Batch, JobRecord


async def _batch_with_jobs(db_session, project, statuses):
    batch = Batch(id=str(uuid.uuid4()), project_id=project.id, kind="scene_image",
                  status="running")
    db_session.add(batch)
    await db_session.flush()
    jobs = []
    for st in statuses:
        j = JobRecord(kind="scene_image", status=st, batch_id=batch.id, payload={},
                      attempts=(3 if st == "failed" else 0),
                      error=("boom" if st == "failed" else None))
        db_session.add(j)
        jobs.append(j)
    await db_session.commit()
    return batch, jobs


@pytest.mark.asyncio
async def test_get_batch_aggregate_counts(client, db_session, project):
    batch, _ = await _batch_with_jobs(
        db_session, project,
        ["queued", "running", "completed", "completed", "failed", "cancelled"],
    )
    resp = await client.get(f"/api/batches/{batch.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {
        "queued": 1, "running": 1, "completed": 2, "failed": 1,
        "cancelled": 1, "total": 6,
    }
    assert body["status"] == "running"  # work still in flight


@pytest.mark.asyncio
async def test_derived_status_all_completed(client, db_session, project):
    batch, _ = await _batch_with_jobs(db_session, project, ["completed", "completed"])
    body = (await client.get(f"/api/batches/{batch.id}")).json()
    assert body["status"] == "completed"


@pytest.mark.asyncio
async def test_list_project_batches_newest_first(client, db_session, project):
    b1, _ = await _batch_with_jobs(db_session, project, ["queued"])
    b2, _ = await _batch_with_jobs(db_session, project, ["completed"])
    resp = await client.get(f"/api/projects/{project.id}/batches")
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()]
    assert set(ids) == {b1.id, b2.id}
    assert all("counts" in b for b in resp.json())


@pytest.mark.asyncio
async def test_cancel_only_touches_non_terminal(client, db_session, project):
    batch, jobs = await _batch_with_jobs(
        db_session, project, ["queued", "running", "completed", "failed"],
    )
    resp = await client.post(f"/api/batches/{batch.id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    by_status = {}
    for j in (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == batch.id)
    )).scalars().all():
        by_status.setdefault(j.status, 0)
        by_status[j.status] += 1
    # queued + running -> cancelled (2 total); completed + failed untouched.
    assert by_status["cancelled"] == 2
    assert by_status["completed"] == 1
    assert by_status["failed"] == 1


@pytest.mark.asyncio
async def test_retry_failed_resets_only_failed(client, db_session, project):
    batch, _ = await _batch_with_jobs(
        db_session, project, ["failed", "failed", "cancelled", "completed"],
    )
    resp = await client.post(f"/api/batches/{batch.id}/retry-failed")
    assert resp.status_code == 200

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == batch.id)
    )).scalars().all()
    by_status = {}
    for j in jobs:
        by_status[j.status] = by_status.get(j.status, 0) + 1
    # both failed -> queued; cancelled stays cancelled; completed untouched.
    assert by_status.get("queued") == 2
    assert by_status.get("cancelled") == 1
    assert by_status.get("completed") == 1
    assert "failed" not in by_status
    for j in jobs:
        if j.status == "queued":
            assert j.attempts == 0
            assert j.error is None


@pytest.mark.asyncio
async def test_get_batch_includes_job_detail_list_does_not(client, db_session, project):
    batch, _ = await _batch_with_jobs(db_session, project, ["completed", "failed"])
    # Single-batch view carries per-job detail (status + error) for the panel.
    single = (await client.get(f"/api/batches/{batch.id}")).json()
    assert "jobs" in single and len(single["jobs"]) == 2
    failed = next(j for j in single["jobs"] if j["status"] == "failed")
    assert failed["error"] == "boom"
    # List view stays light — no per-job detail.
    listed = (await client.get(f"/api/projects/{project.id}/batches")).json()
    assert all("jobs" not in b for b in listed)


@pytest.mark.asyncio
async def test_get_missing_batch_404(client):
    resp = await client.get(f"/api/batches/{uuid.uuid4()}")
    assert resp.status_code == 404

"""KAN-29 — deferred batch start (overnight scheduling)."""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from database import Scene, JobRecord
from services.batch_service import parse_run_after
from services.job_worker import claim_jobs


async def _scene(db_session, project):
    s = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1,
              slugline="S", screenplay="x", sort_order=0)
    db_session.add(s)
    await db_session.commit()
    return s


# ── parse_run_after ─────────────────────────────────────────────────────────

def test_parse_relative_and_tonight():
    now = datetime(2026, 8, 5, 9, 0, 0)
    assert parse_run_after("+4h", now=now) == now + timedelta(hours=4)
    assert parse_run_after("+30m", now=now) == now + timedelta(minutes=30)
    assert parse_run_after("+2d", now=now) == now + timedelta(days=2)
    # tonight -> next 23:00
    assert parse_run_after("tonight", now=now) == now.replace(hour=23, minute=0, second=0)
    # after 23:00 rolls to tomorrow
    late = datetime(2026, 8, 5, 23, 30, 0)
    assert parse_run_after("tonight", now=late).day == 6


def test_parse_iso_and_empty():
    assert parse_run_after(None) is None
    assert parse_run_after("") is None
    got = parse_run_after("2026-12-31T23:00:00")
    assert got == datetime(2026, 12, 31, 23, 0, 0)


def test_parse_bad_raises():
    for bad in ("soon", "4h", "+h", "next week", "+4x"):
        with pytest.raises(ValueError):
            parse_run_after(bad)


# ── endpoint: bad run_after -> 422 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_bad_run_after_returns_422(client, db_session, project):
    await _scene(db_session, project)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "run_after": "whenever",
    })
    assert resp.status_code == 422
    # Nothing created.
    from database import Batch
    assert (await db_session.execute(select(Batch))).scalars().first() is None


# ── worker skips future jobs, then claims once the clock passes ────────────

@pytest.mark.asyncio
async def test_scheduled_batch_skipped_then_picked_up(client, db_session, project):
    await _scene(db_session, project)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "run_after": "+4h",
    })
    assert resp.status_code == 201
    batch_id = resp.json()["batch_id"]

    # Reported as scheduled while waiting.
    body = (await client.get(f"/api/batches/{batch_id}")).json()
    assert body["status"] == "scheduled"
    assert body["run_after"] is not None

    # Every child job carries the future scheduled_after.
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == batch_id)
    )).scalars().all()
    assert jobs and all(j.scheduled_after is not None for j in jobs)
    run_at = jobs[0].scheduled_after

    # Before the start time: worker claims nothing.
    async with db_session as _:  # reuse the session
        claimed = await claim_jobs(db_session, 10, now=run_at - timedelta(minutes=1))
    assert claimed == []

    # After the clock passes it (injected, no sleep): claimable.
    claimed = await claim_jobs(db_session, 10, now=run_at + timedelta(seconds=1))
    assert {j.job_id for j in claimed} == {j.job_id for j in jobs}

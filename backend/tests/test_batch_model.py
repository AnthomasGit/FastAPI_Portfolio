"""KAN-25 — Batch model + FK from JobRecord."""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import Batch, JobRecord


@pytest.mark.asyncio
async def test_batch_owns_child_jobs(db_session, project):
    batch = Batch(
        id=str(uuid.uuid4()), project_id=project.id, name="Overnight render",
        kind="scene_image", spec={"scope": "project", "variants": 1},
        status="pending",
    )
    db_session.add(batch)
    await db_session.flush()

    for i in range(3):
        db_session.add(JobRecord(kind="scene_image", status="queued",
                                 batch_id=batch.id, payload={"i": i}))
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(Batch).where(Batch.id == batch.id).options(selectinload(Batch.jobs))
        )
    ).scalars().one()
    assert fetched.name == "Overnight render"
    assert fetched.status == "pending"
    assert fetched.spec["scope"] == "project"
    assert len(fetched.jobs) == 3
    assert {j.batch_id for j in fetched.jobs} == {batch.id}


@pytest.mark.asyncio
async def test_job_batch_backref(db_session, project):
    batch = Batch(id=str(uuid.uuid4()), project_id=project.id, kind="video")
    db_session.add(batch)
    await db_session.flush()
    job = JobRecord(kind="video", status="queued", batch_id=batch.id, payload={})
    db_session.add(job)
    await db_session.commit()

    fetched = (
        await db_session.execute(
            select(JobRecord).where(JobRecord.job_id == job.job_id)
            .options(selectinload(JobRecord.batch))
        )
    ).scalars().one()
    assert fetched.batch.id == batch.id
    assert fetched.batch.kind == "video"


@pytest.mark.asyncio
async def test_batchless_job_still_valid(db_session):
    # batch_id is optional — Phase 0 jobs carry none.
    job = JobRecord(kind="scene_image", status="queued", payload={})
    db_session.add(job)
    await db_session.commit()
    assert job.batch_id is None

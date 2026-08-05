"""KAN-18 — JobRecord extended into the job-queue backbone."""
import uuid

import pytest
from sqlalchemy import select

from database import JobRecord


@pytest.mark.asyncio
async def test_jobrecord_defaults(db_session):
    job = JobRecord(kind="asset_txt2img", payload={"prompt": "a cat", "seed": 42})
    db_session.add(job)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(JobRecord).where(JobRecord.job_id == job.job_id))
    ).scalars().one()

    assert fetched.kind == "asset_txt2img"
    assert fetched.payload == {"prompt": "a cat", "seed": 42}
    assert fetched.status == "queued"
    assert fetched.attempts == 0
    assert fetched.max_attempts == 3
    assert fetched.priority == 0
    assert fetched.batch_id is None
    assert fetched.depends_on_job_id is None
    assert fetched.scheduled_after is None
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_jobrecord_legacy_columns_nullable(db_session):
    # New kinds leave model_name/query null — must not raise.
    job = JobRecord(kind="scene_image", payload={})
    db_session.add(job)
    await db_session.commit()
    assert job.model_name is None
    assert job.query is None


@pytest.mark.asyncio
async def test_jobrecord_depends_on_self_fk(db_session):
    parent = JobRecord(kind="mesh", payload={})
    db_session.add(parent)
    await db_session.flush()

    child = JobRecord(kind="rig", payload={}, depends_on_job_id=parent.job_id)
    db_session.add(child)
    await db_session.commit()

    assert child.depends_on_job_id == parent.job_id

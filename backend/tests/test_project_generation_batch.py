"""KAN-28 — POST /api/generate/project/{id} builds a batch, submits nothing."""
import os
import uuid

import pytest
import respx
from sqlalchemy import select

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from services.comfyui_client import COMFY_API_URL
from database import Batch, JobRecord, Scene, GeneratedImage


@pytest.mark.asyncio
async def test_project_generation_creates_one_batch_no_sync_submit(client, db_session, project):
    for i in range(5):
        db_session.add(Scene(id=str(uuid.uuid4()), project_id=project.id,
                             scene_number=i + 1, slugline=f"S{i}", screenplay="x",
                             sort_order=i))
    await db_session.commit()

    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(return_value=None)
        resp = await client.post(f"/api/generate/project/{project.id}")
        assert resp.status_code == 200
        # Nothing was submitted to ComfyUI synchronously — the worker owns that.
        assert submit_route.call_count == 0

    body = resp.json()
    assert "batch_id" in body
    assert len(body["generation_ids"]) == 5  # key preserved for existing callers

    batches = (await db_session.execute(select(Batch))).scalars().all()
    assert len(batches) == 1
    assert batches[0].id == body["batch_id"]

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == body["batch_id"])
    )).scalars().all()
    assert len(jobs) == 5
    assert all(j.status == "queued" and j.kind == "scene_image" for j in jobs)

    gens = (await db_session.execute(select(GeneratedImage))).scalars().all()
    assert {g.id for g in gens} == set(body["generation_ids"])


@pytest.mark.asyncio
async def test_project_generation_missing_project_404(client):
    resp = await client.post(f"/api/generate/project/{uuid.uuid4()}")
    assert resp.status_code == 404

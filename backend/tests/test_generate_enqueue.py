"""KAN-23 — image endpoints enqueue; worker drives to completion.

The defining test: POST the generate endpoint, NEVER call the status endpoint,
run the worker, and assert the owning row reaches completed. Progress no longer
depends on a browser polling.
"""
import os
import uuid

import pytest
import respx
from httpx import Response
from sqlalchemy import select

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from database import GeneratedImage, AssetImage, JobRecord
from services.comfyui_client import COMFY_API_URL
from services.job_worker import JobWorker


def _history_completed(prompt_id):
    return {prompt_id: {"status": {"status_str": "success"}, "outputs": {}}}


@pytest.mark.asyncio
async def test_scene_generate_enqueues_and_worker_completes(client, session_factory, scene):
    prompt_id = str(uuid.uuid4())

    # 1) Enqueue via the endpoint — returns immediately, no submit happens here.
    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        resp = await client.post(f"/api/generate/scene/{scene.id}")
        assert resp.status_code == 200
        gen_id = resp.json()["generation_id"]
        assert submit_route.call_count == 0  # endpoint did not submit

    # A queued job and a queued row now exist.
    async with session_factory() as db:
        gen = await db.get(GeneratedImage, gen_id)
        assert gen.status == "queued"
        job = (
            await db.execute(select(JobRecord).where(JobRecord.entity_id == gen_id))
        ).scalars().first()
        assert job is not None and job.kind == "scene_image"

    # 2) Run the worker (no status endpoint ever called).
    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=_history_completed(prompt_id))
        )
        await worker.tick()

    # 3) The row is completed, with the worker-written image_url.
    async with session_factory() as db:
        gen = await db.get(GeneratedImage, gen_id)
        assert gen.status == "completed"
        assert gen.image_url


@pytest.mark.asyncio
async def test_asset_generate_enqueues_and_worker_completes(client, session_factory, project, character):
    prompt_id = str(uuid.uuid4())

    with respx.mock:
        submit_route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        resp = await client.post(
            "/api/asset-images/generate",
            json={"project_id": project.id, "entity_type": "characters",
                  "prompt": "a knight"},
        )
        assert resp.status_code == 202
        asset_id = resp.json()["asset_image_id"]
        assert submit_route.call_count == 0

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=_history_completed(prompt_id))
        )
        await worker.tick()

    async with session_factory() as db:
        asset = await db.get(AssetImage, asset_id)
        assert asset.status == "completed"
        assert asset.image_url and asset.image_url.endswith("_00001_.png")

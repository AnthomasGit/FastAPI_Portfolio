import os
import json
import copy
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import Response
import respx

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from services.comfyui_client import COMFY_API_URL, inject
from database import SceneStaging, SceneCapture, GeneratedImage, JobRecord
from sqlalchemy import select

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..", "workflows")

FAKE_WORKFLOW = {
    "2": {"inputs": {"text": "", "clip": ["1", 1]}, "class_type": "CLIPTextEncode"},
    "4": {"inputs": {"image": "depth.png"}, "class_type": "LoadImage"},
    "6": {
        "inputs": {"strength": 0.8, "positive": ["2", 0]},
        "class_type": "ControlNetApplyAdvanced",
    },
    "8": {"inputs": {"seed": 1, "model": ["1", 0]}, "class_type": "KSampler"},
    "10": {"inputs": {"filename_prefix": "ComfyUI"}, "class_type": "SaveImage"},
}

FAKE_NODE_MAP = {
    "prompt_node": "2",
    "seed_node": "8",
    "output_node": "10",
    "image_node": "4",
    "controlnet_node": "6",
    "ref_image_node": "4",
}


@pytest_asyncio.fixture
async def capture(db_session, scene):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.flush()

    cap = SceneCapture(
        staging_id=staging.id,
        camera={"position": [0, 1, 5], "fov": 40},
        staging_snapshot={"blockout": [], "placements": []},
        depth_map_url="depth_test-capture.png",
        width=512,
        height=512,
    )
    db_session.add(cap)
    await db_session.commit()
    await db_session.refresh(cap)
    return cap


# ── Trigger: capture → scene prompt resolution ─────────────────────────────

@pytest.mark.asyncio
@patch("services.controlled_gen_service.load_workflow")
@patch("services.controlled_gen_service.load_node_map")
async def test_controlled_resolves_scene_prompt_and_writes_job(
    mock_load_node_map, mock_load_workflow, client, scene, capture, db_session,
):
    mock_load_workflow.return_value = copy.deepcopy(FAKE_WORKFLOW)
    mock_load_node_map.return_value = dict(FAKE_NODE_MAP)

    # Generation now enqueues a job (the worker submits later); no /prompt call here.
    resp = await client.post(
        "/api/generate/controlled",
        json={"capture_id": capture.id, "params": {"seed": 4242}},
    )
    assert resp.status_code == 202
    gen_id = resp.json()["generation_id"]

    result = await db_session.execute(
        select(GeneratedImage).where(GeneratedImage.id == gen_id)
    )
    gen = result.scalars().first()
    assert gen is not None
    assert gen.kind == "beauty"
    assert gen.capture_id == capture.id
    assert gen.scene_id == scene.id
    assert gen.status == "queued"
    # prompt was resolved capture -> staging -> scene
    assert scene.slugline in gen.prompt
    assert gen.params["seed"] == 4242
    assert gen.params["workflow"] == "image_klein_beauty"

    job_result = await db_session.execute(
        select(JobRecord).where(JobRecord.entity_id == gen_id)
    )
    job = job_result.scalars().first()
    assert job is not None
    assert job.kind == "controlled_image"
    assert job.entity_type == "generated_image"
    assert job.status == "queued"
    assert scene.slugline in job.query
    # source/ref files resolved at enqueue and carried on the payload
    assert job.payload["seed"] == 4242
    assert job.payload["image"]
    assert job.payload["ref_image"]
    assert job.payload["generation_id"] == gen_id


@pytest.mark.asyncio
@patch("services.controlled_gen_service.load_workflow")
@patch("services.controlled_gen_service.load_node_map")
async def test_controlled_prompt_override_wins(
    mock_load_node_map, mock_load_workflow, client, capture, db_session,
):
    mock_load_workflow.return_value = copy.deepcopy(FAKE_WORKFLOW)
    mock_load_node_map.return_value = dict(FAKE_NODE_MAP)

    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": str(uuid.uuid4())})
        )
        resp = await client.post(
            "/api/generate/controlled",
            json={"capture_id": capture.id, "prompt_override": "OVERRIDE_PROMPT"},
        )
        assert resp.status_code == 202

    result = await db_session.execute(
        select(GeneratedImage).where(GeneratedImage.id == resp.json()["generation_id"])
    )
    gen = result.scalars().first()
    assert gen.prompt == "OVERRIDE_PROMPT"


@pytest.mark.asyncio
@patch("services.controlled_gen_service.load_workflow")
@patch("services.controlled_gen_service.load_node_map")
async def test_controlled_submit_failure_marks_failed_with_error(
    mock_load_node_map, mock_load_workflow, client, capture, db_session, session_factory,
):
    """Submit now happens in the worker; a terminal failure surfaces as 'failed'
    through the status endpoint (job -> row mapping)."""
    from services.job_worker import JobWorker

    mock_load_workflow.return_value = copy.deepcopy(FAKE_WORKFLOW)
    mock_load_node_map.return_value = dict(FAKE_NODE_MAP)

    resp = await client.post(
        "/api/generate/controlled", json={"capture_id": capture.id}
    )
    assert resp.status_code == 202
    gen_id = resp.json()["generation_id"]

    # Make the single attempt terminal.
    job = (
        await db_session.execute(select(JobRecord).where(JobRecord.entity_id == gen_id))
    ).scalars().first()
    job.max_attempts = 1
    await db_session.commit()

    worker = JobWorker(session_factory=session_factory, max_inflight=1, retry_backoff_base=0)
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(return_value=Response(500, text="boom"))
        await worker.tick()

    async with session_factory() as db:
        job = await db.get(JobRecord, job.job_id)
        assert job.status == "failed"
        assert "ComfyUI submit failed" in (job.error or "")

    # Status endpoint maps the failed job onto the row.
    resp = await client.get(f"/api/generate/status/{gen_id}")
    assert resp.json()["status"] == "failed"


# ── Injection snapshot against the real committed workflow ─────────────────

def test_beauty_injection_snapshot():
    """Snapshot against the real committed beauty workflow.

    (This replaces an older snapshot test pointed at
    ``image_controlnet_ipadapter``, a workflow that was never created because
    neither ControlNet nor IP-Adapter is installed — the beauty pass uses Flux
    Klein 9B img2img instead.)
    """
    with open(os.path.join(WORKFLOW_DIR, "image_klein_beauty.json")) as f:
        workflow = json.load(f)
    with open(os.path.join(WORKFLOW_DIR, "image_klein_beauty.map.json")) as f:
        node_map = json.load(f)

    original = copy.deepcopy(workflow)
    injected = inject(workflow, node_map, {
        "prompt": "SNAPSHOT_PROMPT",
        "seed": 999,
        "filename_prefix": "job-snap",
        "image": "color_abc.png",
        "ref_image": "character_ref.png",
    })

    # Exact expected result: the original graph with only the five injection
    # points changed. Note the seed node is RandomNoise (noise_seed), not a
    # KSampler — inject() handles both.
    expected = original
    expected[node_map["prompt_node"]]["inputs"]["text"] = "SNAPSHOT_PROMPT"
    expected[node_map["seed_node"]]["inputs"]["noise_seed"] = 999
    expected[node_map["output_node"]]["inputs"]["filename_prefix"] = "job-snap"
    expected[node_map["image_node"]]["inputs"]["image"] = "color_abc.png"
    expected[node_map["ref_image_node"]]["inputs"]["image"] = "character_ref.png"

    assert injected == expected


# ── Guards: 404 / 409 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_controlled_404_unknown_capture(client):
    resp = await client.post(
        "/api/generate/controlled", json={"capture_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_controlled_409_when_generation_inflight(
    client, capture, db_session,
):
    # The 409 guard now keys off JOB state: a queued/running controlled job for
    # one of this capture's images means a generation is already in flight.
    inflight = GeneratedImage(
        capture_id=capture.id, kind="controlled", status="queued"
    )
    db_session.add(inflight)
    await db_session.flush()
    job = JobRecord(
        kind="controlled_image",
        status="running",
        entity_type="generated_image",
        entity_id=inflight.id,
        payload={},
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.post(
        "/api/generate/controlled", json={"capture_id": capture.id}
    )
    assert resp.status_code == 409


# ── Status flow through the existing poller ────────────────────────────────

@pytest_asyncio.fixture
async def processing_generation(db_session, scene, capture):
    gen = GeneratedImage(
        scene_id=scene.id,
        capture_id=capture.id,
        kind="controlled",
        status="processing",
        prompt_id=str(uuid.uuid4()),
        image_url="job_00001_.png",
    )
    db_session.add(gen)
    await db_session.commit()
    await db_session.refresh(gen)
    return gen


@pytest.mark.asyncio
async def test_status_flow_history_completed(client, processing_generation):
    prompt_id = processing_generation.prompt_id
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {
                    "status": {"status_str": "completed"},
                    "outputs": {"10": {"images": [{"filename": "job_00001_.png"}]}},
                }
            })
        )
        resp = await client.get(
            f"/api/generate/status/{processing_generation.id}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_status_flow_history_error(client, processing_generation):
    prompt_id = processing_generation.prompt_id
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {
                    "status": {"status_str": "error"},
                    "outputs": {},
                }
            })
        )
        resp = await client.get(
            f"/api/generate/status/{processing_generation.id}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_status_flow_still_processing_when_not_in_history(
    client, processing_generation,
):
    prompt_id = processing_generation.prompt_id
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={})
        )
        resp = await client.get(
            f"/api/generate/status/{processing_generation.id}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"


# ── Captures list nests generation attempts ────────────────────────────────

@pytest.mark.asyncio
async def test_captures_list_includes_generated_images(
    client, scene, capture, db_session,
):
    gen = GeneratedImage(
        scene_id=scene.id,
        capture_id=capture.id,
        kind="beauty",
        status="completed",
        params={"seed": 42, "workflow": "image_klein_beauty"},
    )
    db_session.add(gen)
    await db_session.commit()

    resp = await client.get(f"/api/scenes/{scene.id}/staging/captures")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    attempts = data[0]["generated_images"]
    assert len(attempts) == 1
    assert attempts[0]["kind"] == "beauty"
    assert attempts[0]["params"]["seed"] == 42

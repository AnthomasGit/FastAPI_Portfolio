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

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(
            "/api/generate/controlled",
            json={"capture_id": capture.id, "params": {"controlnet_strength": 0.65}},
        )
        assert resp.status_code == 202
        gen_id = resp.json()["generation_id"]

    result = await db_session.execute(
        select(GeneratedImage).where(GeneratedImage.id == gen_id)
    )
    gen = result.scalars().first()
    assert gen is not None
    assert gen.kind == "controlled"
    assert gen.capture_id == capture.id
    assert gen.scene_id == scene.id
    assert gen.status == "processing"
    assert gen.prompt_id == prompt_id
    # prompt was resolved capture -> staging -> scene
    assert scene.slugline in gen.prompt
    assert gen.params["controlnet_strength"] == 0.65
    assert gen.params["seed"] is not None

    job_result = await db_session.execute(
        select(JobRecord).where(JobRecord.entity_id == gen_id)
    )
    job = job_result.scalars().first()
    assert job is not None
    assert job.job_type == "controlled_image"
    assert job.entity_type == "generated_image"
    assert job.status == "processing"
    assert scene.slugline in job.query


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
    mock_load_node_map, mock_load_workflow, client, capture, db_session,
):
    mock_load_workflow.return_value = copy.deepcopy(FAKE_WORKFLOW)
    mock_load_node_map.return_value = dict(FAKE_NODE_MAP)

    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(500, text="boom")
        )
        resp = await client.post(
            "/api/generate/controlled", json={"capture_id": capture.id}
        )
        assert resp.status_code == 202

    result = await db_session.execute(
        select(GeneratedImage).where(GeneratedImage.id == resp.json()["generation_id"])
    )
    gen = result.scalars().first()
    assert gen.status == "failed"
    assert "ComfyUI submit failed" in gen.error

    job_result = await db_session.execute(
        select(JobRecord).where(JobRecord.entity_id == gen.id)
    )
    job = job_result.scalars().first()
    assert job.status == "failed"
    assert job.finished_at is not None


# ── Injection snapshot against the real committed workflow ─────────────────

def test_controlled_injection_snapshot():
    with open(os.path.join(WORKFLOW_DIR, "image_controlnet_ipadapter.json")) as f:
        workflow = json.load(f)
    with open(os.path.join(WORKFLOW_DIR, "image_controlnet_ipadapter.map.json")) as f:
        node_map = json.load(f)

    original = copy.deepcopy(workflow)
    injected = inject(workflow, node_map, {
        "prompt": "SNAPSHOT_PROMPT",
        "seed": 999,
        "filename_prefix": "job-snap",
        "image": "depth_abc.png",
        "controlnet_strength": 0.55,
    })

    # Exact expected result: the original graph with only the five injection
    # points changed.
    expected = original
    expected[node_map["prompt_node"]]["inputs"]["text"] = "SNAPSHOT_PROMPT"
    expected[node_map["seed_node"]]["inputs"]["seed"] = 999
    expected[node_map["output_node"]]["inputs"]["filename_prefix"] = "job-snap"
    expected[node_map["image_node"]]["inputs"]["image"] = "depth_abc.png"
    expected[node_map["controlnet_node"]]["inputs"]["strength"] = 0.55

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
    inflight = GeneratedImage(
        capture_id=capture.id, kind="controlled", status="processing"
    )
    db_session.add(inflight)
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
        kind="controlled",
        status="completed",
        params={"controlnet_strength": 0.8, "seed": 42},
    )
    db_session.add(gen)
    await db_session.commit()

    resp = await client.get(f"/api/scenes/{scene.id}/staging/captures")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    attempts = data[0]["generated_images"]
    assert len(attempts) == 1
    assert attempts[0]["kind"] == "controlled"
    assert attempts[0]["params"]["controlnet_strength"] == 0.8

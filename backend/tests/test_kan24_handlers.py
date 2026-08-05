"""KAN-24 — per-handler build_workflow injection for the ported kinds.

video is exercised via build_video in test_video_workflows.py; here we cover the
mesh and controlled_image handlers and confirm the registry is complete.
"""
import os
import uuid
from unittest.mock import patch

import pytest

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

# Importing the services registers their handlers.
import services.asset3d_service  # noqa: F401
import services.controlled_gen_service  # noqa: F401
import services.video_service  # noqa: F401
from services.job_handlers import HANDLERS
from services.comfyui_client import load_node_map


def test_all_kan24_kinds_registered():
    for kind in ("video", "controlled_image", "mesh"):
        assert kind in HANDLERS


@pytest.mark.asyncio
async def test_build_mesh_injects_image_seed_and_prefix(db_session):
    from services.asset3d_service import build_mesh

    fake_workflow = {"1": {"inputs": {"image": ""}}, "2": {"inputs": {"seed": 0}},
                     "3": {"inputs": {"filename_prefix": ""}}}
    fake_map = {"image_node": "1", "seed_node": "2", "output_node": "3"}

    with patch("services.asset3d_service.load_workflow", return_value=fake_workflow), \
         patch("services.asset3d_service.load_node_map", return_value=fake_map):
        payload = {
            "workflow_name": "MeshWithTexturing_6steps_example",
            "entity_type": "character",
            "project_id": "proj1",
            "source_url": "tpose.png",
            "seed": 555,
            "dual_output": True,
            "job_id": "MESHJOB",
        }
        workflow, meta = await build_mesh(payload, db_session)

    assert workflow["1"]["inputs"]["image"] == "tpose.png"
    assert workflow["2"]["inputs"]["seed"] == 555
    assert workflow["3"]["inputs"]["filename_prefix"] == "meshes/proj1/characters/MESHJOB"
    assert meta["prefix"] == "meshes/proj1/characters/MESHJOB"


@pytest.mark.asyncio
async def test_build_mesh_placeholder_raises(db_session):
    from services.asset3d_service import build_mesh
    with patch("services.asset3d_service.load_workflow", return_value={"_placeholder": True}):
        with pytest.raises(RuntimeError):
            await build_mesh(
                {"workflow_name": "x", "entity_type": "character",
                 "project_id": "p", "source_url": "s.png", "seed": 1,
                 "dual_output": True, "job_id": "j"},
                db_session,
            )


@pytest.mark.asyncio
async def test_build_controlled_image_injection(db_session):
    from services.controlled_gen_service import build_controlled_image, WORKFLOW_NAME

    payload = {
        "prompt": "cinematic beauty pass",
        "seed": 321,
        "image": "color_map.png",
        "ref_image": "character_ref.png",
        "job_id": "CTRLJOB",
    }
    workflow, meta = await build_controlled_image(payload, db_session)
    node_map = load_node_map(WORKFLOW_NAME)

    assert workflow[node_map["prompt_node"]]["inputs"]["text"] == "cinematic beauty pass"
    assert workflow[node_map["image_node"]]["inputs"]["image"] == "color_map.png"
    assert workflow[node_map["ref_image_node"]]["inputs"]["image"] == "character_ref.png"
    assert workflow[node_map["output_node"]]["inputs"]["filename_prefix"] == "CTRLJOB"
    assert meta["image_url"] == "CTRLJOB_00001_.png"

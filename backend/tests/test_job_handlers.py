"""KAN-19 — job handler registry: build_workflow injection + on_complete.

These exercise the handlers directly (no HTTP, no ComfyUI submit). The node ids
asserted against come from each workflow's ``.map.json``.
"""
import os
import uuid

import pytest

from database import AssetImage, GeneratedImage
import services.job_handlers as jh
from services.job_handlers import HANDLERS


def _node_text(workflow, node_id, field):
    return workflow[node_id]["inputs"][field]


@pytest.mark.asyncio
async def test_registry_kinds():
    # The three image kinds register here; other services (video, mesh,
    # controlled_image) register their own kinds on import.
    assert {"asset_txt2img", "asset_img2img", "scene_image"} <= set(HANDLERS)


@pytest.mark.asyncio
async def test_asset_txt2img_injection(db_session):
    payload = {
        "project_id": "proj1",
        "entity_type": "character",
        "prompt": "a knight",
        "job_id": "JOB123",
        "seed": 777,
        "width": 1280,
        "height": 720,
    }
    workflow, meta = await HANDLERS["asset_txt2img"].build_workflow(payload, db_session)

    # map: prompt_node 57:27, seed_node 57:3, output_node 9, w/h 57:13
    assert _node_text(workflow, "57:27", "text") == "a knight"
    assert _node_text(workflow, "57:3", "seed") == 777
    assert _node_text(workflow, "9", "filename_prefix") == "assets/proj1/characters/JOB123"
    assert _node_text(workflow, "57:13", "width") == 1280
    assert _node_text(workflow, "57:13", "height") == 720

    assert meta["image_url"] == "assets/proj1/characters/JOB123_00001_.png"
    assert meta["seed"] == 777
    assert meta["job_id"] == "JOB123"


@pytest.mark.asyncio
async def test_scene_image_injection(db_session):
    payload = {"prompt": "wide establishing shot", "job_id": "SCENEJOB", "seed": 42}
    workflow, meta = await HANDLERS["scene_image"].build_workflow(payload, db_session)

    assert _node_text(workflow, "57:27", "text") == "wide establishing shot"
    assert _node_text(workflow, "57:3", "seed") == 42
    assert _node_text(workflow, "9", "filename_prefix") == "SCENEJOB"
    assert meta["image_url"] == "SCENEJOB_00001_.png"


@pytest.mark.asyncio
async def test_asset_img2img_injection(db_session, project, tmp_path, monkeypatch):
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))

    # Seed a completed asset to use as the img2img source.
    src = AssetImage(
        id=str(uuid.uuid4()),
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="completed",
        image_url="assets/x/characters/src_00001_.png",
    )
    db_session.add(src)
    await db_session.commit()

    # Provide the on-disk source so the copy into COMFY_INPUT_DIR succeeds.
    os.makedirs(os.path.join(str(out_dir), "assets/x/characters"), exist_ok=True)
    with open(os.path.join(str(out_dir), src.image_url), "wb") as f:
        f.write(b"fake")

    payload = {
        "project_id": project.id,
        "entity_type": "character",
        "prompt": "make it rain",
        "source_asset_image_id": src.id,
        "job_id": "IMG2JOB",
        "seed": 5,
    }
    workflow, meta = await HANDLERS["asset_img2img"].build_workflow(payload, db_session)

    # map: prompt_node 75:74, seed_node 75:73, image_node 76, output_node 9
    assert _node_text(workflow, "75:74", "text") == "make it rain"
    assert _node_text(workflow, "75:73", "noise_seed") == 5
    assert _node_text(workflow, "76", "image") == "IMG2JOB_source.png"
    assert _node_text(workflow, "9", "filename_prefix").endswith("/IMG2JOB")
    assert meta["image_url"].endswith("/IMG2JOB_00001_.png")


@pytest.mark.asyncio
async def test_img2img_no_source_raises(db_session, project):
    payload = {
        "project_id": project.id,
        "entity_type": "character",
        "prompt": "x",
        "job_id": "J",
    }
    with pytest.raises(ValueError):
        await HANDLERS["asset_img2img"].build_workflow(payload, db_session)


@pytest.mark.asyncio
async def test_on_complete_scene_marks_completed(db_session, scene):
    gen = GeneratedImage(id=str(uuid.uuid4()), scene_id=scene.id, status="processing")
    db_session.add(gen)
    await db_session.commit()

    await HANDLERS["scene_image"].on_complete(
        {"generation_id": gen.id, "image_url": "SCENEJOB_00001_.png"}, {}, db_session
    )
    await db_session.refresh(gen)
    assert gen.status == "completed"
    assert gen.image_url == "SCENEJOB_00001_.png"


@pytest.mark.asyncio
async def test_asset_txt2img_selects_krea2_workflow_and_aspect(db_session):
    """A workflow key routes to the Krea2 graph; size becomes an aspect ratio."""
    payload = {
        "project_id": "proj1",
        "entity_type": "character",
        "prompt": "a knight",
        "job_id": "JOBK2",
        "seed": 999,
        "width": 768,
        "height": 1024,
        "workflow": "krea2_turbo",
    }
    workflow, meta = await HANDLERS["asset_txt2img"].build_workflow(payload, db_session)

    assert meta["workflow"] == "image_krea2_turbo"
    # Krea2 map: prompt 247, seed 256 (easy seed), output 241 (SaveImage),
    # aspect_ratio 255. Portrait 768×1024 -> nearest 3:4.
    assert _node_text(workflow, "247", "text") == "a knight"
    assert _node_text(workflow, "256", "seed") == 999
    assert _node_text(workflow, "241", "filename_prefix") == "assets/proj1/characters/JOBK2"
    assert workflow["241"]["class_type"] == "SaveImage"
    assert _node_text(workflow, "255", "aspect_ratio") == "3:4 (Portrait Standard)"


@pytest.mark.asyncio
async def test_asset_txt2img_unknown_workflow_falls_back_to_default(db_session):
    payload = {
        "project_id": "p", "entity_type": "prop", "prompt": "x",
        "job_id": "J", "seed": 1, "workflow": "nope",
    }
    _workflow, meta = await HANDLERS["asset_txt2img"].build_workflow(payload, db_session)
    assert meta["workflow"] == "image_z_image_turbo"

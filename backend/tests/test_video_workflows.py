"""Multi-workflow clip generation: registry routing, validation, injection.

The expensive failure this suite guards against is a graph that submits
successfully with a slot left unfilled — ComfyUI reports success either way and
the mistake only surfaces much later as a missing output file.
"""

import json
import os
import uuid

import pytest

from database import GeneratedVideo, Reference, Scene, Shot
from services.comfyui_client import inject, load_node_map, load_workflow
from services.video_service import (
    DEFAULT_WORKFLOW,
    VIDEO_WORKFLOWS,
    generate_video,
    list_workflows,
)

COMFY_INPUT_DIR = os.environ["COMFY_INPUT_DIR"]


# ── Registry ────────────────────────────────────────────────────────────


def test_default_workflow_is_registered():
    assert DEFAULT_WORKFLOW in VIDEO_WORKFLOWS


def test_list_workflows_exposes_id_and_capabilities():
    entries = {e["id"]: e for e in list_workflows()}
    assert "ltx_msr" in entries and "ltx_i2v" in entries
    msr = entries["ltx_msr"]
    assert msr["max_refs"] == 4
    assert msr["needs_still"] is False
    assert msr["dual_prompt"] is True
    assert msr["reference_frame_count"] is True
    # i2v is the still-driven one and takes no references.
    assert entries["ltx_i2v"]["needs_still"] is True
    assert entries["ltx_i2v"]["max_refs"] == 0
    assert entries["ltx_i2v"]["reference_frame_count"] is False


def test_every_registered_workflow_has_a_committed_pair():
    for cfg in VIDEO_WORKFLOWS.values():
        workflow = load_workflow(cfg["workflow"])
        node_map = load_node_map(cfg["workflow"])
        assert workflow and node_map


# ── MSR injection fills every declared slot ─────────────────────────────


def test_msr_injection_fills_all_reference_slots_and_both_prompts():
    name = VIDEO_WORKFLOWS["ltx_msr"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    injected = inject(workflow, node_map, {
        "image": "a.png", "image2": "b.png", "image3": "c.png", "image4": "d.png",
        "background_image": "bg.png",
        "global_prompt": "GLOBAL", "local_prompts": "LOCAL",
        "negative_prompt": "NEG",
        "seed": 4242, "filename_prefix": "job-1",
        "width": 544, "height": 960, "fps": 25, "duration": 5,
    })

    assert injected[node_map["image_node"]]["inputs"]["image"] == "a.png"
    assert injected[node_map["image2_node"]]["inputs"]["image"] == "b.png"
    assert injected[node_map["image3_node"]]["inputs"]["image"] == "c.png"
    assert injected[node_map["image4_node"]]["inputs"]["image"] == "d.png"
    assert injected[node_map["background_node"]]["inputs"]["image"] == "bg.png"

    # Both prompts live on the same PromptRelayEncode node, different fields.
    relay = injected[node_map["global_prompt_node"]]["inputs"]
    assert relay["global_prompt"] == "GLOBAL"
    assert relay["local_prompts"] == "LOCAL"

    assert injected[node_map["negative_node"]]["inputs"]["text"] == "NEG"
    assert injected[node_map["seed_node"]]["inputs"]["noise_seed"] == 4242
    assert injected[node_map["output_node"]]["inputs"]["filename_prefix"] == "job-1"
    # INTConstant/FloatConstant primitives carry a plain "value".
    assert injected[node_map["width_node"]]["inputs"]["value"] == 544
    assert injected[node_map["height_node"]]["inputs"]["value"] == 960
    assert injected[node_map["fps_node"]]["inputs"]["value"] == 25
    assert injected[node_map["duration_node"]]["inputs"]["value"] == 5


def test_msr_reference_frame_count_injects_as_string():
    """LiconMSR's frame_count widget is a string ("17"), not an int."""
    name = VIDEO_WORKFLOWS["ltx_msr"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    injected = inject(workflow, node_map, {"reference_frame_count": "24"})
    node = injected[node_map["reference_frame_count_node"]]
    assert node["inputs"]["frame_count"] == "24"


def test_inject_ignores_keys_the_workflow_does_not_map():
    """i2v has no reference slots; passing them must not corrupt the graph."""
    name = VIDEO_WORKFLOWS["ltx_i2v"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)
    before = json.dumps(workflow, sort_keys=True)

    inject(workflow, node_map, {"image3": "nope.png", "background_image": "nope.png"})
    assert json.dumps(workflow, sort_keys=True) == before


# ── Validation happens before a row is created ──────────────────────────


@pytest.mark.asyncio
async def test_unknown_workflow_raises(db_session):
    with pytest.raises(ValueError, match="Unknown video workflow"):
        await generate_video(db_session, workflow_key="nope")


@pytest.mark.asyncio
async def test_msr_requires_at_least_one_reference(db_session):
    with pytest.raises(ValueError, match="at least one reference"):
        await generate_video(db_session, workflow_key="ltx_msr", reference_ids=[])


@pytest.mark.asyncio
async def test_msr_rejects_more_references_than_slots(db_session, scene):
    ref_ids = []
    for _ in range(5):
        ref = Reference(
            id=str(uuid.uuid4()), entity_type="character",
            entity_id=str(uuid.uuid4()), url="x.png",
        )
        db_session.add(ref)
        ref_ids.append(ref.id)
    await db_session.commit()

    with pytest.raises(ValueError, match="at most 4 references"):
        await generate_video(db_session, workflow_key="ltx_msr", reference_ids=ref_ids)


@pytest.mark.asyncio
async def test_i2v_requires_a_still(db_session):
    with pytest.raises(ValueError, match="requires a completed still"):
        await generate_video(db_session, workflow_key="ltx_i2v")


@pytest.mark.asyncio
async def test_missing_reference_file_raises_before_any_row_is_created(db_session):
    """A dangling LoadImage would make ComfyUI reject the whole graph silently."""
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url="definitely_not_on_disk.png",
    )
    db_session.add(ref)
    await db_session.commit()

    with pytest.raises(ValueError, match="missing from the input directory"):
        await generate_video(
            db_session, workflow_key="ltx_msr", reference_ids=[ref.id]
        )

    rows = (await db_session.execute(__import__("sqlalchemy").select(GeneratedVideo))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_unknown_reference_id_raises(db_session):
    with pytest.raises(ValueError, match="not found"):
        await generate_video(
            db_session, workflow_key="ltx_msr", reference_ids=[str(uuid.uuid4())]
        )


# ── Happy path: the row records workflow + settings, keyed to the shot ──


@pytest.mark.asyncio
async def test_msr_clip_attaches_to_shot_and_records_params(db_session, scene, monkeypatch):
    filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, filename), "wb") as f:
        f.write(b"fake")

    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=filename,
    )
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add_all([ref, shot])
    await db_session.commit()

    async def fake_submit(_workflow):
        return "prompt-123"

    monkeypatch.setattr("services.video_service.submit", fake_submit)

    video_id = await generate_video(
        db_session,
        workflow_key="ltx_msr",
        shot=shot,
        reference_ids=[ref.id],
        global_prompt="Image 1: a man",
        local_prompts="He waves.",
        params={"seed": 7, "width": 544, "height": 960, "fps": 25, "duration": 5},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.status == "processing"
    assert video.shot_id == shot.id
    assert video.source_image_id is None      # MSR consumes no still
    assert video.scene_id == scene.id
    assert video.params["workflow"] == "ltx_msr"
    assert video.params["seed"] == 7
    assert video.params["fps"] == 25
    assert video.prompt == "He waves."
    # Not supplied -> falls back to the default rather than being omitted.
    assert video.params["reference_frame_count"] == 17


@pytest.mark.asyncio
async def test_msr_reference_frame_count_is_overridable(db_session, scene, monkeypatch):
    filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, filename), "wb") as f:
        f.write(b"fake")
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=filename,
    )
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add_all([ref, shot])
    await db_session.commit()

    async def fake_submit(_workflow):
        return "prompt-123"

    monkeypatch.setattr("services.video_service.submit", fake_submit)

    video_id = await generate_video(
        db_session,
        workflow_key="ltx_msr",
        shot=shot,
        reference_ids=[ref.id],
        params={"reference_frame_count": 32},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.params["reference_frame_count"] == 32


@pytest.mark.asyncio
async def test_i2v_ignores_reference_frame_count(db_session, scene, monkeypatch):
    """i2v's registry entry doesn't declare the capability; the param is dropped."""
    from database import GeneratedImage

    image = GeneratedImage(
        id=str(uuid.uuid4()), scene_id=scene.id, project_id=scene.project_id,
        status="completed", image_url="still.png",
    )
    db_session.add(image)
    await db_session.commit()
    # _stage_source_for_load copies from COMFY_OUTPUT_DIR; point it at the
    # same test dir so the fake file it needs is where it looks.
    monkeypatch.setattr("services.video_service.COMFY_OUTPUT_DIR", COMFY_INPUT_DIR)
    with open(os.path.join(COMFY_INPUT_DIR, "still.png"), "wb") as f:
        f.write(b"fake")

    async def fake_submit(_workflow):
        return "prompt-123"

    monkeypatch.setattr("services.video_service.submit", fake_submit)

    video_id = await generate_video(
        db_session, workflow_key="ltx_i2v", image=image,
        params={"reference_frame_count": 99},
    )
    video = await db_session.get(GeneratedVideo, video_id)
    assert "reference_frame_count" not in video.params

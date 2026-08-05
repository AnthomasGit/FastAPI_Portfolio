"""Multi-workflow clip generation: registry routing, validation, injection.

The expensive failure this suite guards against is a graph that submits
successfully with a slot left unfilled — ComfyUI reports success either way and
the mistake only surfaces much later as a missing output file.
"""

import json
import os
import uuid

import pytest
from sqlalchemy import select

from database import DrivingVideo, GeneratedVideo, JobRecord, Reference, ReferenceAudio, Scene, Shot
from services.comfyui_client import inject, load_node_map, load_workflow
from services.video_service import (
    DEFAULT_WORKFLOW,
    VIDEO_WORKFLOWS,
    _prune_autogrow_slots,
    build_video,
    generate_video,
    list_workflows,
)

COMFY_INPUT_DIR = os.environ["COMFY_INPUT_DIR"]


async def _submitted_workflow(db, video_id):
    """The graph the worker would submit: build_video() on the enqueued job's
    payload. Generation now enqueues rather than submitting inline, so injection
    is asserted against this rather than a captured submit() call."""
    job = (
        await db.execute(select(JobRecord).where(JobRecord.entity_id == video_id))
    ).scalars().first()
    workflow, _ = await build_video(job.payload, db)
    return workflow


# ── Registry ────────────────────────────────────────────────────────────


def test_default_workflow_is_registered():
    assert DEFAULT_WORKFLOW in VIDEO_WORKFLOWS


def test_list_workflows_exposes_id_and_capabilities():
    entries = {e["id"]: e for e in list_workflows()}
    assert "ltx_msr" in entries and "ltx_i2v" in entries and "scail2_anim" in entries

    msr = entries["ltx_msr"]
    assert msr["max_refs"] == 4
    assert msr["needs_still"] is False
    assert msr["dual_prompt"] is True
    msr_settings = {s["id"]: s for s in msr["settings"]}
    # Matches LiconMSR's actual COMBO (confirmed via ComfyUI /object_info),
    # not a free-form int -- an out-of-list value fails ComfyUI validation.
    assert msr_settings["reference_frame_count"]["options"] == [17, 25, 33, 41, 49, 57, 65]
    # Backend-only injection wiring must not leak to the client.
    assert "inject" not in msr_settings["reference_frame_count"]
    assert "str_value" not in msr_settings["reference_frame_count"]

    # i2v is the still-driven one, takes no references, and has no settings.
    assert entries["ltx_i2v"]["needs_still"] is True
    assert entries["ltx_i2v"]["max_refs"] == 0
    assert entries["ltx_i2v"]["settings"] == []

    scail2 = entries["scail2_anim"]
    assert scail2["driving_video"] is True
    assert scail2["max_refs"] == 1
    scail2_settings = {s["id"]: s for s in scail2["settings"]}
    assert set(scail2_settings) == {"frames", "pose_strength"}


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


# ── SCAIL-2 injection: one setting fans out to two nodes ────────────────


def test_scail2_frames_fans_out_to_length_and_driving_frames():
    """`frames` must set BOTH nodes or driving motion and output length desync."""
    name = VIDEO_WORKFLOWS["scail2_anim"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    injected = inject(workflow, node_map, {
        "image": "ref.png",
        "driving_video": "drive.mp4",
        "length": 49,
        "driving_frames": 49,
        "pose_strength": 0.75,
        "prompt": "POS",
        "negative_prompt": "NEG",
        "seed": 999,
        "filename_prefix": "job-2",
    })

    assert injected[node_map["image_node"]]["inputs"]["image"] == "ref.png"
    assert injected[node_map["video_node"]]["inputs"]["video"] == "drive.mp4"
    # length_node and pose_strength_node are the SAME node (101) -- must not
    # clobber each other.
    node_101 = injected[node_map["length_node"]]["inputs"]
    assert node_101["length"] == 49
    assert node_101["pose_strength"] == 0.75
    # driving_frames_node is a different node (113) sharing the video load.
    assert injected[node_map["driving_frames_node"]]["inputs"]["frame_load_cap"] == 49
    assert injected[node_map["prompt_node"]]["inputs"]["text"] == "POS"
    assert injected[node_map["negative_node"]]["inputs"]["text"] == "NEG"
    assert injected[node_map["seed_node"]]["inputs"]["seed"] == 999
    assert injected[node_map["output_node"]]["inputs"]["filename_prefix"] == "job-2"


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

    rows = (await db_session.execute(select(GeneratedVideo))).scalars().all()
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
    assert video.status == "queued"
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

    video_id = await generate_video(
        db_session,
        workflow_key="ltx_msr",
        shot=shot,
        reference_ids=[ref.id],
        params={"reference_frame_count": 33},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.params["reference_frame_count"] == 33


@pytest.mark.asyncio
async def test_msr_rejects_reference_frame_count_outside_the_combo(db_session, scene):
    """32 isn't one of LiconMSR's actual COMBO values -- ComfyUI would reject it."""
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url="x.png",
    )
    db_session.add(ref)
    await db_session.commit()

    with pytest.raises(ValueError, match=r"must be one of \[17, 25, 33, 41, 49, 57, 65\]"):
        await generate_video(
            db_session, workflow_key="ltx_msr", reference_ids=[ref.id],
            params={"reference_frame_count": 32},
        )


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

    video_id = await generate_video(
        db_session, workflow_key="ltx_i2v", image=image,
        params={"reference_frame_count": 99},
    )
    video = await db_session.get(GeneratedVideo, video_id)
    assert "reference_frame_count" not in video.params


# ── SCAIL-2: driving-video validation and happy path ─────────────────────


@pytest.mark.asyncio
async def test_scail2_requires_driving_video(db_session, scene):
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url="x.png",
    )
    db_session.add(ref)
    await db_session.commit()

    with pytest.raises(ValueError, match="requires a driving video"):
        await generate_video(
            db_session, workflow_key="scail2_anim", reference_ids=[ref.id]
        )


@pytest.mark.asyncio
async def test_scail2_rejects_frames_outside_range(db_session, scene):
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url="x.png",
    )
    dv = DrivingVideo(id=str(uuid.uuid4()), video_url="drive.mp4")
    db_session.add_all([ref, dv])
    await db_session.commit()

    with pytest.raises(ValueError, match="must be ≤ 161"):
        await generate_video(
            db_session, workflow_key="scail2_anim", reference_ids=[ref.id],
            driving_video_id=dv.id, params={"frames": 999},
        )


@pytest.mark.asyncio
async def test_missing_driving_video_file_raises_before_any_row_is_created(db_session, scene):
    """A dangling VHS_LoadVideo would make ComfyUI reject the whole graph silently."""
    ref_filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, ref_filename), "wb") as f:
        f.write(b"fake")
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=ref_filename,
    )
    dv = DrivingVideo(id=str(uuid.uuid4()), video_url="definitely_not_on_disk.mp4")
    db_session.add_all([ref, dv])
    await db_session.commit()

    with pytest.raises(ValueError, match="missing from the input directory"):
        await generate_video(
            db_session, workflow_key="scail2_anim", reference_ids=[ref.id],
            driving_video_id=dv.id,
        )

    rows = (await db_session.execute(select(GeneratedVideo))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_unknown_driving_video_id_raises(db_session, scene):
    ref_filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, ref_filename), "wb") as f:
        f.write(b"fake")
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=ref_filename,
    )
    db_session.add(ref)
    await db_session.commit()

    with pytest.raises(ValueError, match="not found"):
        await generate_video(
            db_session, workflow_key="scail2_anim", reference_ids=[ref.id],
            driving_video_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_scail2_happy_path_records_frames_and_pose_strength(db_session, scene, monkeypatch):
    ref_filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, ref_filename), "wb") as f:
        f.write(b"fake")
    video_filename = f"{uuid.uuid4()}.mp4"
    with open(os.path.join(COMFY_INPUT_DIR, video_filename), "wb") as f:
        f.write(b"fake")

    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=ref_filename,
    )
    dv = DrivingVideo(id=str(uuid.uuid4()), video_url=video_filename)
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="2A")
    db_session.add_all([ref, dv, shot])
    await db_session.commit()

    video_id = await generate_video(
        db_session,
        workflow_key="scail2_anim",
        shot=shot,
        reference_ids=[ref.id],
        driving_video_id=dv.id,
        motion_prompt="A knight waves.",
        params={"frames": 49, "pose_strength": 0.5},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.status == "queued"
    assert video.shot_id == shot.id
    assert video.params["workflow"] == "scail2_anim"
    assert video.params["frames"] == 49
    assert video.params["pose_strength"] == 0.5
    assert video.prompt == "A knight waves."


# ── MiniMax H3 R2V: registry, injection, autogrow pruning ────────────────


def test_r2v_registry_capabilities_and_settings():
    entries = {e["id"]: e for e in list_workflows()}
    assert "minimax_h3_r2v" in entries
    r2v = entries["minimax_h3_r2v"]
    assert r2v["needs_still"] is False
    assert r2v["max_refs"] == 9
    assert r2v["max_ref_videos"] == 3
    assert r2v["max_ref_audios"] == 3
    assert r2v["dual_prompt"] is False
    # Locations are pickable identity/style references (no background plate).
    assert r2v["locations_as_refs"] is True

    settings = {s["id"]: s for s in r2v["settings"]}
    # Sampler defaults to res_multistep (H3's recommended sampler), and the
    # scheduler defaults to beta -- it beats simple for reference-heavy prompts.
    assert settings["sampler_name"]["default"] == "res_multistep"
    assert "res_multistep" in settings["sampler_name"]["options"]
    assert settings["scheduler"]["default"] == "beta"
    assert set(["beta", "normal", "simple"]).issubset(settings["scheduler"]["options"])
    # Backend-only injection wiring must not leak (autogrow_slots is a cfg flag,
    # not a setting, so it should not appear as a knob either).
    assert "autogrow_slots" not in settings


def test_r2v_injection_fills_all_slots_and_sampler_knobs():
    name = VIDEO_WORKFLOWS["minimax_h3_r2v"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    overrides = {
        "prompt": "A duel.", "seed": 555, "filename_prefix": "job-r2v",
        "sampler_name": "res_multistep", "scheduler": "beta", "steps": 24,
        "duration": 8, "aspect_ratio": "9:16 (Portrait Widescreen)", "megapixels": 0.5,
    }
    for i in range(9):
        overrides["image" if i == 0 else f"image{i + 1}"] = f"img{i}.png"
    for i in range(3):
        overrides["ref_video" if i == 0 else f"ref_video{i + 1}"] = f"vid{i}.mp4"
        overrides["ref_audio" if i == 0 else f"ref_audio{i + 1}"] = f"aud{i}.wav"

    injected = inject(workflow, node_map, overrides)

    # Prompt is a PrimitiveStringMultiline -> "value", not "text".
    assert injected[node_map["prompt_node"]]["inputs"]["value"] == "A duel."
    assert injected[node_map["seed_node"]]["inputs"]["noise_seed"] == 555
    assert injected[node_map["output_node"]]["inputs"]["filename_prefix"] == "job-r2v"
    assert injected[node_map["sampler_node"]]["inputs"]["sampler_name"] == "res_multistep"
    # scheduler + steps live on the SAME BasicScheduler node; must not clobber.
    sched = injected[node_map["scheduler_node"]]["inputs"]
    assert sched["scheduler"] == "beta"
    assert sched["steps"] == 24
    assert injected[node_map["duration_node"]]["inputs"]["value"] == 8
    res = injected[node_map["aspect_ratio_node"]]["inputs"]
    assert res["aspect_ratio"] == "9:16 (Portrait Widescreen)"
    assert res["megapixels"] == 0.5

    for i, node_id in enumerate(node_map["image_slots"]):
        assert injected[node_id]["inputs"]["image"] == f"img{i}.png"
    for i, node_id in enumerate(node_map["video_slots"]):
        assert injected[node_id]["inputs"]["file"] == f"vid{i}.mp4"
    for i, node_id in enumerate(node_map["audio_slots"]):
        assert injected[node_id]["inputs"]["audio"] == f"aud{i}.wav"


def test_r2v_prune_drops_unused_slots_and_their_references():
    name = VIDEO_WORKFLOWS["minimax_h3_r2v"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    # Keep 2 images, 1 video, 0 audios.
    pruned = _prune_autogrow_slots(workflow, node_map, 2, 1, 0)

    # Kept slots survive; trailing ones are gone.
    assert node_map["image_slots"][0] in pruned
    assert node_map["image_slots"][1] in pruned
    for node_id in node_map["image_slots"][2:]:
        assert node_id not in pruned
    assert node_map["video_slots"][0] in pruned
    for node_id in node_map["video_slots"][1:]:
        assert node_id not in pruned
    for node_id in node_map["video_component_nodes"][1:]:
        assert node_id not in pruned
    for node_id in node_map["audio_slots"]:
        assert node_id not in pruned

    # The autogrow node's dangling references are gone too, so ComfyUI won't
    # reject the graph for pointing at deleted loader nodes.
    ref_inputs = pruned[node_map["ref_node"]]["inputs"]
    assert "ref_images.ref_image_0" in ref_inputs
    assert "ref_images.ref_image_2" not in ref_inputs
    assert "ref_videos.ref_video_0" in ref_inputs
    assert "ref_videos.ref_video_1" not in ref_inputs
    assert "ref_video_audios.ref_video_audio_1" not in ref_inputs
    assert "ref_audios.ref_audio_0" not in ref_inputs


@pytest.mark.asyncio
async def test_r2v_rejects_too_many_reference_videos(db_session, scene):
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url="x.png",
    )
    db_session.add(ref)
    await db_session.commit()

    with pytest.raises(ValueError, match="at most 3 reference videos"):
        await generate_video(
            db_session, workflow_key="minimax_h3_r2v", reference_ids=[ref.id],
            ref_video_ids=["a", "b", "c", "d"],
        )


@pytest.mark.asyncio
async def test_r2v_missing_audio_file_raises_before_any_row_is_created(db_session, scene):
    ref_filename = f"{uuid.uuid4()}.png"
    with open(os.path.join(COMFY_INPUT_DIR, ref_filename), "wb") as f:
        f.write(b"fake")
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=ref_filename,
    )
    ra = ReferenceAudio(id=str(uuid.uuid4()), audio_url="definitely_not_on_disk.wav")
    db_session.add_all([ref, ra])
    await db_session.commit()

    with pytest.raises(ValueError, match="missing from the input directory"):
        await generate_video(
            db_session, workflow_key="minimax_h3_r2v", reference_ids=[ref.id],
            ref_audio_ids=[ra.id],
        )
    rows = (await db_session.execute(select(GeneratedVideo))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_r2v_happy_path_prunes_and_submits(db_session, scene, monkeypatch):
    # Stage one ref image, one ref video, one audio clip on disk.
    img = f"{uuid.uuid4()}.png"
    vid = f"{uuid.uuid4()}.mp4"
    aud = f"{uuid.uuid4()}.wav"
    for fn in (img, vid, aud):
        with open(os.path.join(COMFY_INPUT_DIR, fn), "wb") as f:
            f.write(b"fake")

    ref = Reference(
        id=str(uuid.uuid4()), entity_type="character",
        entity_id=str(uuid.uuid4()), url=img,
    )
    dv = DrivingVideo(id=str(uuid.uuid4()), video_url=vid)
    ra = ReferenceAudio(id=str(uuid.uuid4()), audio_url=aud)
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add_all([ref, dv, ra, shot])
    await db_session.commit()

    video_id = await generate_video(
        db_session,
        workflow_key="minimax_h3_r2v",
        shot=shot,
        reference_ids=[ref.id],
        ref_video_ids=[dv.id],
        ref_audio_ids=[ra.id],
        motion_prompt="They fight.",
        params={"scheduler": "normal", "steps": 18},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.status == "queued"
    assert video.shot_id == shot.id
    assert video.source_image_id is None
    assert video.params["workflow"] == "minimax_h3_r2v"
    assert video.params["scheduler"] == "normal"
    assert video.params["steps"] == 18

    # The graph the worker will submit kept exactly the filled slots, pruned the rest.
    submitted = await _submitted_workflow(db_session, video_id)
    node_map = load_node_map("video_minimax_h3_r2v")
    assert submitted[node_map["image_slots"][0]]["inputs"]["image"] == img
    assert node_map["image_slots"][1] not in submitted
    assert submitted[node_map["video_slots"][0]]["inputs"]["file"] == vid
    assert node_map["video_slots"][1] not in submitted
    assert submitted[node_map["audio_slots"][0]]["inputs"]["audio"] == aud
    assert node_map["audio_slots"][1] not in submitted
    # Sampler default (res_multistep) applied even though only scheduler was set.
    assert submitted[node_map["sampler_node"]]["inputs"]["sampler_name"] == "res_multistep"


# ── MiniMax H3 I2V: still-driven with an optional last-frame keyframe ─────


def test_i2v_h3_registry_capabilities():
    entries = {e["id"]: e for e in list_workflows()}
    assert "minimax_h3_i2v" in entries
    i2v = entries["minimax_h3_i2v"]
    assert i2v["needs_still"] is False
    assert i2v["first_frame"] is True
    assert i2v["last_frame"] is True
    assert i2v["max_refs"] == 0
    settings = {s["id"]: s for s in i2v["settings"]}
    assert settings["sampler_name"]["default"] == "res_multistep"
    assert "sampler_name" in settings and "scheduler" in settings


def test_i2v_h3_injection_fills_frames_prompt_and_sampler():
    name = VIDEO_WORKFLOWS["minimax_h3_i2v"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    injected = inject(workflow, node_map, {
        "image": "still.png", "last_frame": "end.png",
        "prompt": "It moves.", "seed": 77, "filename_prefix": "job-i2v",
        "sampler_name": "res_multistep", "scheduler": "beta", "steps": 22,
        "duration": 6, "aspect_ratio": "16:9 (Widescreen)", "megapixels": 0.4,
    })

    assert injected[node_map["image_node"]]["inputs"]["image"] == "still.png"
    assert injected[node_map["last_frame_node"]]["inputs"]["image"] == "end.png"
    # I2V's prompt is inline on the MiniMaxH3ImageToVideo node ("prompt" field).
    assert injected[node_map["prompt_node"]]["inputs"]["prompt"] == "It moves."
    assert injected[node_map["seed_node"]]["inputs"]["noise_seed"] == 77
    assert injected[node_map["output_node"]]["inputs"]["filename_prefix"] == "job-i2v"
    assert injected[node_map["sampler_node"]]["inputs"]["sampler_name"] == "res_multistep"
    sched = injected[node_map["scheduler_node"]]["inputs"]
    assert sched["scheduler"] == "beta" and sched["steps"] == 22


def test_i2v_h3_prune_removes_unused_last_frame():
    from services.video_service import _prune_optional_last_frame
    name = VIDEO_WORKFLOWS["minimax_h3_i2v"]["workflow"]
    workflow = load_workflow(name)
    node_map = load_node_map(name)

    pruned = _prune_optional_last_frame(workflow, node_map)
    assert node_map["last_frame_node"] not in pruned
    assert "last_frame" not in pruned[node_map["ref_node"]]["inputs"]
    # first_frame slot survives.
    assert node_map["image_node"] in pruned


@pytest.mark.asyncio
async def test_i2v_h3_happy_path_prunes_last_frame_when_absent(db_session, scene, monkeypatch):
    from database import GeneratedImage

    image = GeneratedImage(
        id=str(uuid.uuid4()), scene_id=scene.id, project_id=scene.project_id,
        status="completed", image_url="still.png",
    )
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add_all([image, shot])
    await db_session.commit()

    monkeypatch.setattr("services.video_service.COMFY_OUTPUT_DIR", COMFY_INPUT_DIR)
    with open(os.path.join(COMFY_INPUT_DIR, "still.png"), "wb") as f:
        f.write(b"fake")

    video_id = await generate_video(
        db_session, workflow_key="minimax_h3_i2v", image=image, shot=shot,
        motion_prompt="A slow push in.", params={"steps": 16},
    )

    video = await db_session.get(GeneratedVideo, video_id)
    assert video.status == "queued"
    assert video.params["workflow"] == "minimax_h3_i2v"

    node_map = load_node_map("video_minimax_h3_i2v")
    submitted = await _submitted_workflow(db_session, video_id)
    # first_frame got the staged still; the unused last_frame slot is gone.
    assert submitted[node_map["image_node"]]["inputs"]["image"] == f"{image.id}_source.png"
    assert node_map["last_frame_node"] not in submitted
    assert "last_frame" not in submitted[node_map["ref_node"]]["inputs"]


@pytest.mark.asyncio
async def test_i2v_h3_requires_a_first_frame(db_session, scene):
    """No still and no first-frame reference is a caller error, not a failed run."""
    with pytest.raises(ValueError, match="requires a first-frame image"):
        await generate_video(db_session, workflow_key="minimax_h3_i2v", shot=None)


@pytest.mark.asyncio
async def test_i2v_h3_first_frame_reference_overrides_still(db_session, scene, monkeypatch):
    """An explicit first-frame reference is used as the input image over the still."""
    still_fn = "still.png"
    ref_fn = f"{uuid.uuid4()}.png"
    monkeypatch.setattr("services.video_service.COMFY_OUTPUT_DIR", COMFY_INPUT_DIR)
    for fn in (still_fn, ref_fn):
        with open(os.path.join(COMFY_INPUT_DIR, fn), "wb") as f:
            f.write(b"fake")

    from database import GeneratedImage
    image = GeneratedImage(
        id=str(uuid.uuid4()), scene_id=scene.id, project_id=scene.project_id,
        status="completed", image_url=still_fn,
    )
    ref = Reference(
        id=str(uuid.uuid4()), entity_type="location",
        entity_id=str(uuid.uuid4()), url=ref_fn,
    )
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add_all([image, ref, shot])
    await db_session.commit()

    video_id = await generate_video(
        db_session, workflow_key="minimax_h3_i2v", image=image, shot=shot,
        first_frame_reference_id=ref.id, motion_prompt="Go.",
    )

    node_map = load_node_map("video_minimax_h3_i2v")
    submitted = await _submitted_workflow(db_session, video_id)
    first_frame = submitted[node_map["image_node"]]["inputs"]["image"]
    # The reference file wins over the staged still ("<id>_source.png").
    assert first_frame == ref_fn

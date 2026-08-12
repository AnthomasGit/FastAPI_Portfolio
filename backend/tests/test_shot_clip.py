"""The `shot_clip` job kind — per-shot MiniMax H3 reference-to-video.

The pruning assertions here guard the dominant failure mode of this graph: R2V
ships all 9 image / 3 video / 3 audio slots present, each pointing at a
placeholder filename. Leaving an unfilled one in makes ComfyUI reject the ENTIRE
graph at validation while still reporting success, so it only surfaces much
later as a phantom "no output file". Anything that lets a slot survive unfilled
is a silent corruption, not a visible bug.
"""
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from database import (
    AssetImage, Character, Location, Prop, Reference, Shot, GeneratedVideo,
    scene_characters, scene_locations, scene_props,
)
import services.job_handlers as jh
from services.shot_clip_service import (
    build_shot_clip, resolve_shot_reference_files, create_shot_clip_rows,
)

MAP = json.load(open(os.path.join(os.path.dirname(__file__), "..", "workflows",
                                  "video_minimax_h3_r2v.map.json")))
REF_NODE = MAP["ref_node"]


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    return out_dir, in_dir


_ETYPE = {Character: "character", Location: "location", Prop: "prop"}


async def _with_image(db_session, project, out_dir, model, name, **kw):
    """An entity plus a Reference holding its art.

    Art reaches generation through References now, not a global canonical
    column: the scene's own pick (scene_<type>.reference_id) wins, else the
    entity's newest reference.
    """
    etype = _ETYPE[model]
    rel = f"assets/{project.id}/{name}.png"
    os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(out_dir, rel), "wb") as f:
        f.write(b"img")
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type=etype, status="completed", image_url=rel)
    db_session.add(asset)
    await db_session.flush()
    entity = model(id=str(uuid.uuid4()), project_id=project.id, name=name, **kw)
    db_session.add(entity)
    await db_session.flush()
    ref = Reference(id=str(uuid.uuid4()), entity_type=etype, entity_id=entity.id,
                    role="moodboard", url=rel, asset_image_id=asset.id)
    db_session.add(ref)
    await db_session.flush()
    entity._ref_id = ref.id          # tests assert on the staged filename
    return entity


async def _link(db_session, scene, *, chars=(), locs=(), props=()):
    for c in chars:
        await db_session.execute(scene_characters.insert().values(
            scene_id=scene.id, character_id=c.id))
    for l in locs:
        await db_session.execute(scene_locations.insert().values(
            scene_id=scene.id, location_id=l.id))
    for p in props:
        await db_session.execute(scene_props.insert().values(
            scene_id=scene.id, prop_id=p.id))


async def _shot(db_session, scene, **kw):
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A",
                clip_prompt="subject_definitions:\n<Subject 1> ...", **kw)
    db_session.add(shot)
    await db_session.commit()
    return shot


def _payload(shot, **kw):
    return {"shot_id": shot.id, "workflow_key": "minimax_h3_r2v",
            "seed": 42, "job_id": "job-1", **kw}


# ── reference resolution + ordering ────────────────────────────────────────

@pytest.mark.asyncio
async def test_references_ordered_characters_location_props(db_session, project, scene, dirs):
    out_dir, _ = dirs
    zed = await _with_image(db_session, project, out_dir, Character, "Zed")
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    bar = await _with_image(db_session, project, out_dir, Location, "Bar")
    knife = await _with_image(db_session, project, out_dir, Prop, "Knife")
    await _link(db_session, scene, chars=[zed, ada], locs=[bar], props=[knife])
    shot = await _shot(db_session, scene)

    files, entities = await resolve_shot_reference_files(shot, db_session, 9)
    assert [e.name for _, e in entities] == ["Ada", "Zed", "Bar", "Knife"]
    # index-aligned with the filenames that fill image1..image4
    assert len(files) == 4
    assert files[2] == f"{bar._ref_id}_ref.png"


@pytest.mark.asyncio
async def test_entities_without_a_primary_image_are_skipped(db_session, project, scene, dirs):
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    naked = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Nothing")
    db_session.add(naked)
    await db_session.flush()
    await _link(db_session, scene, chars=[ada], props=[naked])
    shot = await _shot(db_session, scene)

    files, entities = await resolve_shot_reference_files(shot, db_session, 9)
    assert [e.name for _, e in entities] == ["Ada"]
    assert len(files) == 1


@pytest.mark.asyncio
async def test_extras_beyond_slot_count_dropped_with_named_warning(
        db_session, project, scene, dirs, caplog):
    out_dir, _ = dirs
    chars = [await _with_image(db_session, project, out_dir, Character, f"C{i:02d}")
             for i in range(11)]
    await _link(db_session, scene, chars=chars)
    shot = await _shot(db_session, scene)

    with caplog.at_level("WARNING"):
        files, entities = await resolve_shot_reference_files(shot, db_session, 9)
    assert len(files) == 9 and len(entities) == 9
    # The omission must be visible in the job log, naming what was dropped.
    assert "C09" in caplog.text and "C10" in caplog.text


# ── pruning: the silent-corruption guard ───────────────────────────────────

@pytest.mark.asyncio
async def test_unused_slots_are_pruned(db_session, project, scene, dirs):
    out_dir, _ = dirs
    chars = [await _with_image(db_session, project, out_dir, Character, f"C{i}")
             for i in range(3)]
    await _link(db_session, scene, chars=chars)
    shot = await _shot(db_session, scene)

    workflow, meta = await build_shot_clip(_payload(shot), db_session)

    # 3 refs used -> image slots 4..9 (nodes 142..147) must be gone.
    for node_id in MAP["image_slots"][3:]:
        assert node_id not in workflow, f"unfilled image slot {node_id} survived"
    for node_id in MAP["image_slots"][:3]:
        assert node_id in workflow
    # No ref videos or audios at all -> every one of those loaders is gone.
    for node_id in MAP["video_slots"] + MAP["audio_slots"] + MAP["video_component_nodes"]:
        assert node_id not in workflow, f"unfilled slot {node_id} survived"
    # …and the aggregator's inputs for the dropped slots are gone with them.
    ref_inputs = workflow[REF_NODE]["inputs"]
    for i in range(3, 9):
        assert f"ref_images.ref_image_{i}" not in ref_inputs
    for i in range(3):
        assert f"ref_audios.ref_audio_{i}" not in ref_inputs
        assert f"ref_videos.ref_video_{i}" not in ref_inputs


@pytest.mark.asyncio
async def test_references_land_on_slots_in_order(db_session, project, scene, dirs):
    """Slot N must carry reference N — this is the same ordering the prompt's
    <Subject N> numbering uses, so a mismatch silently describes wrong images."""
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    bar = await _with_image(db_session, project, out_dir, Location, "Bar")
    await _link(db_session, scene, chars=[ada], locs=[bar])
    shot = await _shot(db_session, scene)

    workflow, _ = await build_shot_clip(_payload(shot), db_session)
    assert workflow[MAP["image_node"]]["inputs"]["image"] == f"{ada._ref_id}_ref.png"
    assert workflow[MAP["image2_node"]]["inputs"]["image"] == f"{bar._ref_id}_ref.png"


@pytest.mark.asyncio
async def test_prompt_and_seed_injected(db_session, project, scene, dirs):
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    await _link(db_session, scene, chars=[ada])
    shot = await _shot(db_session, scene)

    workflow, meta = await build_shot_clip(_payload(shot), db_session)
    # R2V's prompt node is a PrimitiveStringMultiline ("value") and its seed
    # node a RandomNoise ("noise_seed") — INJECTION_MAP resolves both.
    assert workflow[MAP["prompt_node"]]["inputs"]["value"].startswith("subject_definitions:")
    assert workflow[MAP["seed_node"]]["inputs"]["noise_seed"] == 42
    assert meta["job_id"] == "job-1" and meta["prefix"] == "job-1"


# ── overrides, audio, failure modes ────────────────────────────────────────

@pytest.mark.asyncio
async def test_clip_refs_override_limits_and_reorders_slots(db_session, project, scene, dirs):
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    bar = await _with_image(db_session, project, out_dir, Location, "Bar")
    knife = await _with_image(db_session, project, out_dir, Prop, "Knife")
    await _link(db_session, scene, chars=[ada], locs=[bar], props=[knife])
    shot = await _shot(db_session, scene, clip_refs=[
        {"entity_type": "location", "entity_id": bar.id},
        {"entity_type": "character", "entity_id": ada.id},
    ])

    workflow, _ = await build_shot_clip(_payload(shot), db_session)
    assert workflow[MAP["image_node"]]["inputs"]["image"] == f"{bar._ref_id}_ref.png"
    assert workflow[MAP["image2_node"]]["inputs"]["image"] == f"{ada._ref_id}_ref.png"
    assert MAP["image_slots"][2] not in workflow      # prop excluded by the override


@pytest.mark.asyncio
async def test_reference_audio_fills_one_slot(db_session, project, scene, dirs):
    out_dir, in_dir = dirs
    from database import ReferenceAudio
    with open(in_dir / "vo.wav", "wb") as f:
        f.write(b"wav")
    ra = ReferenceAudio(id=str(uuid.uuid4()), audio_url="vo.wav")
    db_session.add(ra)
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    await _link(db_session, scene, chars=[ada])
    shot = await _shot(db_session, scene, reference_audio_id=ra.id, audio_role="dialogue")

    import services.video_service as vs
    with patch.object(vs, "COMFY_INPUT_DIR", str(in_dir)):
        workflow, _ = await build_shot_clip(_payload(shot, ref_audio_ids=[ra.id]), db_session)
    assert MAP["audio_slots"][0] in workflow
    assert MAP["audio_slots"][1] not in workflow       # the other two still pruned
    assert "ref_audios.ref_audio_0" in workflow[REF_NODE]["inputs"]


@pytest.mark.asyncio
async def test_missing_audio_file_raises(db_session, project, scene, dirs):
    out_dir, in_dir = dirs
    from database import ReferenceAudio
    ra = ReferenceAudio(id=str(uuid.uuid4()), audio_url="gone.wav")  # never written
    db_session.add(ra)
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    await _link(db_session, scene, chars=[ada])
    shot = await _shot(db_session, scene, reference_audio_id=ra.id)

    import services.video_service as vs
    with patch.object(vs, "COMFY_INPUT_DIR", str(in_dir)):
        with pytest.raises(ValueError, match="missing from the input directory"):
            await build_shot_clip(_payload(shot, ref_audio_ids=[ra.id]), db_session)


@pytest.mark.asyncio
async def test_no_usable_references_raises_actionably(db_session, project, scene, dirs):
    """A reference-to-video graph with no references renders something unrelated
    to the film — worse than an error the queue can show."""
    shot = await _shot(db_session, scene)
    with pytest.raises(ValueError, match="no usable reference images"):
        await build_shot_clip(_payload(shot), db_session)


@pytest.mark.asyncio
async def test_missing_prompt_is_composed_on_the_fly(db_session, project, scene, dirs):
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    await _link(db_session, scene, chars=[ada])
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")  # no clip_prompt
    db_session.add(shot)
    await db_session.commit()

    from services import shot_prompt_service as sps
    fake = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({k: f"{k} body" for k in sps.SECTIONS})))])
    with patch.object(sps.ai_service.client.chat.completions, "create",
                      new=AsyncMock(return_value=fake)):
        workflow, _ = await build_shot_clip(_payload(shot), db_session)

    assert workflow[MAP["prompt_node"]]["inputs"]["value"].startswith("subject_definitions:")
    await db_session.refresh(shot)
    assert shot.clip_prompt  # persisted, so a retry doesn't pay for it again


@pytest.mark.asyncio
async def test_unknown_workflow_key_raises(db_session, project, scene, dirs):
    shot = await _shot(db_session, scene)
    with pytest.raises(ValueError, match="Unknown video workflow"):
        await build_shot_clip(_payload(shot, workflow_key="nope"), db_session)


# ── owning row ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owning_row_links_shot_scene_project(db_session, project, scene):
    shot = await _shot(db_session, scene)
    video = await create_shot_clip_rows(shot, {"workflow": "minimax_h3_r2v"}, 7, db_session)
    assert video.shot_id == shot.id
    assert video.scene_id == scene.id
    assert video.project_id == project.id
    assert video.status == "queued"
    assert video.params["seed"] == 7
    # Reference-driven clips hang off the shot, never a still.
    assert video.source_image_id is None


@pytest.mark.asyncio
async def test_prompt_and_graph_see_the_same_entities(db_session, project, scene, dirs):
    """REGRESSION: the composer and the builder must select identically.

    The compose path once used every scene-linked entity while the render path
    skipped those without a primary image — so a scene with 8 entities and 2
    images produced a prompt describing <Subject 1..8> for a graph that received
    2 pictures. <Subject 3> then referred to something not in slot 3, silently.
    """
    out_dir, _ = dirs
    ada = await _with_image(db_session, project, out_dir, Character, "Ada")
    bar = await _with_image(db_session, project, out_dir, Location, "Bar")
    # Linked to the scene but with no art yet — the common case.
    for name in ("Remote", "Table", "TV"):
        p = Prop(id=str(uuid.uuid4()), project_id=project.id, name=name)
        db_session.add(p)
        await db_session.flush()
        await db_session.execute(scene_props.insert().values(
            scene_id=scene.id, prop_id=p.id))
    await _link(db_session, scene, chars=[ada], locs=[bar])
    shot = await _shot(db_session, scene)

    from services.job_handlers import shot_reference_entities, resolve_scene_entities
    assert len(await resolve_scene_entities(scene.id, db_session)) == 5   # all linked

    selected = await shot_reference_entities(shot, db_session, max_refs=9)
    files, used = await resolve_shot_reference_files(shot, db_session, 9)

    # Only the two with art are selected, and both paths agree exactly.
    assert [e.name for _, e in selected] == ["Ada", "Bar"]
    assert [e.name for _, e in used] == ["Ada", "Bar"]
    assert len(files) == len(selected)


@pytest.mark.asyncio
async def test_selection_is_capped_at_the_slot_count(db_session, project, scene, dirs):
    """The cap lives in the shared selector, so the prompt can never declare
    more subjects than the graph has slots."""
    out_dir, _ = dirs
    chars = [await _with_image(db_session, project, out_dir, Character, f"C{i:02d}")
             for i in range(11)]
    await _link(db_session, scene, chars=chars)
    shot = await _shot(db_session, scene)

    from services.job_handlers import shot_reference_entities
    assert len(await shot_reference_entities(shot, db_session, max_refs=9)) == 9


@pytest.mark.asyncio
async def test_handler_is_registered():
    from services.job_handlers import HANDLERS
    import services.shot_clip_service  # noqa: F401
    assert "shot_clip" in HANDLERS

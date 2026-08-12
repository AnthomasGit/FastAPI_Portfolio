"""Phase 4 (KAN-42): the Location plate feeds scene generation as background."""
import os
import uuid

import pytest

from database import Reference, Character, Location, AssetImage, scene_characters, scene_locations
import services.job_handlers as jh
from services.job_handlers import build_scene_image, resolve_scene_plate


async def _plated_location(db_session, project, scene, name, out_dir, *, plate=True):
    asset_id = None
    rel = None
    if plate:
        rel = f"assets/{project.id}/locations/{name}_plate.png"
        os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(b"plate")
        asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                           entity_type="location", kind="plate",
                           status="completed", image_url=rel)
        db_session.add(asset)
        await db_session.flush()
        asset_id = asset.id
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name=name)
    db_session.add(loc)
    await db_session.flush()
    if asset_id:
        ref = Reference(id=str(uuid.uuid4()), entity_type="location",
                        entity_id=loc.id, role="moodboard",
                        url=rel, asset_image_id=asset_id)
        db_session.add(ref)
        await db_session.flush()
        loc._ref_id = ref.id
    await db_session.execute(
        scene_locations.insert().values(scene_id=scene.id, location_id=loc.id))
    await db_session.commit()
    return loc


async def _canonical_char(db_session, project, scene, name, out_dir):
    rel = f"assets/{project.id}/characters/{name}_00001_.png"
    os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(out_dir, rel), "wb") as f:
        f.write(b"img")
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="character", kind="txt2img",
                       status="completed", image_url=rel)
    db_session.add(asset)
    await db_session.flush()
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name=name)
    db_session.add(char)
    await db_session.flush()
    ref = Reference(id=str(uuid.uuid4()), entity_type="character", entity_id=char.id,
                    role="moodboard", url=rel, asset_image_id=asset.id)
    db_session.add(ref)
    await db_session.flush()
    char._ref_id = ref.id
    await db_session.execute(
        scene_characters.insert().values(scene_id=scene.id, character_id=char.id))
    await db_session.commit()
    return char


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    return out_dir, in_dir


# ── resolve_scene_plate ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_plate_stages_and_returns_filename(db_session, project, scene, dirs):
    out_dir, in_dir = dirs
    loc = await _plated_location(db_session, project, scene, "Hall", str(out_dir))
    fn = await resolve_scene_plate(scene.id, db_session)
    assert fn == f"{loc._ref_id}_ref.png"
    assert os.path.exists(os.path.join(in_dir, fn))  # staged into input dir


@pytest.mark.asyncio
async def test_resolve_plate_none_without_plate(db_session, project, scene, dirs):
    out_dir, _ = dirs
    await _plated_location(db_session, project, scene, "Hall", str(out_dir), plate=False)
    assert await resolve_scene_plate(scene.id, db_session) is None


@pytest.mark.asyncio
async def test_resolve_plate_first_by_name_when_multiple(db_session, project, scene, dirs):
    out_dir, _ = dirs
    await _plated_location(db_session, project, scene, "Zeta", str(out_dir))
    alpha = await _plated_location(db_session, project, scene, "Alpha", str(out_dir))
    fn = await resolve_scene_plate(scene.id, db_session)
    assert fn == f"{alpha._ref_id}_ref.png"  # "Alpha" sorts before "Zeta"


# ── build_scene_image wiring (MSR ref path exposes a background node) ────────

@pytest.mark.asyncio
async def test_plate_lands_on_background_node(db_session, project, scene, dirs):
    out_dir, _ = dirs
    await _canonical_char(db_session, project, scene, "Aldous", str(out_dir))
    loc = await _plated_location(db_session, project, scene, "Hall", str(out_dir))

    workflow, meta = await build_scene_image(
        {"prompt": "a duel", "scene_id": scene.id, "identity_refs": True,
         "job_id": "JOB", "seed": 5}, db_session)

    assert meta["workflow"] == "image_msr_ref"
    assert meta["plate"] is True
    # background_node is node 30 in the MSR ref map.
    assert workflow["30"]["inputs"]["image"] == f"{loc._ref_id}_ref.png"


@pytest.mark.asyncio
async def test_use_plate_false_disables(db_session, project, scene, dirs):
    out_dir, _ = dirs
    await _canonical_char(db_session, project, scene, "Aldous", str(out_dir))
    await _plated_location(db_session, project, scene, "Hall", str(out_dir))

    _, meta = await build_scene_image(
        {"prompt": "a duel", "scene_id": scene.id, "identity_refs": True,
         "use_plate": False, "job_id": "JOB", "seed": 5}, db_session)
    assert meta["plate"] is False


@pytest.mark.asyncio
async def test_plain_workflow_without_background_node_no_error(db_session, project, scene, dirs):
    """A scene on the plain z-image workflow (no background node) falls through
    to plain generation with no error and no plate."""
    out_dir, _ = dirs
    await _plated_location(db_session, project, scene, "Hall", str(out_dir))

    workflow, meta = await build_scene_image(
        {"prompt": "empty", "scene_id": scene.id, "job_id": "JOB", "seed": 5}, db_session)
    assert meta["workflow"] == "image_z_image_turbo"
    assert meta["plate"] is False

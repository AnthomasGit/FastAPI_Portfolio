"""KAN-36 — character identity references fed into scene generation."""
import os
import uuid

import pytest
from sqlalchemy import select

from database import Character, AssetImage, scene_characters
import services.job_handlers as jh
from services.job_handlers import build_scene_image, HANDLERS


async def _canonical_char(db_session, project, scene, name, out_dir, *, canonical=True):
    """A character linked to the scene, optionally with a canonical image on disk."""
    asset_id = None
    if canonical:
        rel = f"assets/{project.id}/characters/{name}_00001_.png"
        os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(b"img")
        asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                           entity_type="character", kind="txt2img",
                           status="completed", image_url=rel)
        db_session.add(asset)
        await db_session.flush()
        asset_id = asset.id
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name=name,
                     canonical_asset_image_id=asset_id)
    db_session.add(char)
    await db_session.flush()
    await db_session.execute(
        scene_characters.insert().values(scene_id=scene.id, character_id=char.id)
    )
    await db_session.commit()
    return char


@pytest.mark.asyncio
async def test_two_canonical_chars_land_on_ref_nodes(db_session, project, scene, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))

    a = await _canonical_char(db_session, project, scene, "Aldous", str(out_dir))
    b = await _canonical_char(db_session, project, scene, "Bex", str(out_dir))

    workflow, meta = await build_scene_image(
        {"prompt": "a duel", "scene_id": scene.id, "identity_refs": True,
         "job_id": "JOB", "seed": 5}, db_session)

    assert meta["workflow"] == "image_msr_ref"
    assert meta["ref_count"] == 2
    # Deterministic by name: Aldous -> subject 1 (node 29), Bex -> subject 2 (33).
    assert workflow["29"]["inputs"]["image"] == f"{a.id}_canon.png"
    assert workflow["33"]["inputs"]["image"] == f"{b.id}_canon.png"
    # LiconMSR needs all 4 subject slots filled: unused ones repeat the last ref.
    assert workflow["40"]["inputs"]["image"] == f"{b.id}_canon.png"
    assert workflow["95"]["inputs"]["image"] == f"{b.id}_canon.png"
    # Files were staged into the input dir.
    assert (in_dir / f"{a.id}_canon.png").exists()


@pytest.mark.asyncio
async def test_char_without_canonical_is_skipped(db_session, project, scene, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))

    a = await _canonical_char(db_session, project, scene, "Aldous", str(out_dir))
    await _canonical_char(db_session, project, scene, "NoImage", str(out_dir), canonical=False)

    workflow, meta = await build_scene_image(
        {"prompt": "x", "scene_id": scene.id, "identity_refs": True,
         "job_id": "J", "seed": 1}, db_session)
    # Only the one with a canonical image contributes; no error. The single ref
    # fills every subject slot (padding).
    assert meta["ref_count"] == 1
    assert workflow["29"]["inputs"]["image"] == f"{a.id}_canon.png"
    assert workflow["95"]["inputs"]["image"] == f"{a.id}_canon.png"


@pytest.mark.asyncio
async def test_more_chars_than_slots_are_capped(db_session, project, scene, tmp_path, monkeypatch, caplog):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))

    # 6 canonical characters, but the MSR workflow maps 4 subject slots.
    for i in range(6):
        await _canonical_char(db_session, project, scene, f"C{i:02d}", str(out_dir))

    import logging
    with caplog.at_level(logging.WARNING):
        workflow, meta = await build_scene_image(
            {"prompt": "crowd", "scene_id": scene.id, "identity_refs": True,
             "job_id": "J", "seed": 1}, db_session)

    assert meta["ref_count"] == 4  # capped to the 4 MSR subject slots
    assert "dropped" in caplog.text.lower()


@pytest.mark.asyncio
async def test_no_canonical_falls_back_to_plain_workflow(db_session, project, scene):
    # No linked characters with canonical images -> plain still workflow.
    workflow, meta = await build_scene_image(
        {"prompt": "empty room", "scene_id": scene.id, "identity_refs": True,
         "job_id": "J", "seed": 1}, db_session)
    assert meta["workflow"] == "image_z_image_turbo"
    assert meta["ref_count"] == 0
    assert workflow["57:27"]["inputs"]["text"] == "empty room"


@pytest.mark.asyncio
async def test_identity_refs_off_uses_plain_workflow(db_session, project, scene, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    await _canonical_char(db_session, project, scene, "Aldous", str(out_dir))

    # identity_refs not set -> plain workflow even though a canonical image exists.
    _wf, meta = await build_scene_image(
        {"prompt": "x", "scene_id": scene.id, "job_id": "J", "seed": 1}, db_session)
    assert meta["workflow"] == "image_z_image_turbo"


# ── canonical-image endpoint ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_canonical_image_endpoint(client, db_session, project, character):
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="character", kind="txt2img", status="completed",
                       image_url="assets/x/characters/hero_00001_.png")
    db_session.add(asset)
    await db_session.commit()

    resp = await client.put(f"/api/characters/{character.id}/canonical-image",
                            json={"asset_image_id": asset.id})
    assert resp.status_code == 200
    assert resp.json()["canonical_asset_image_id"] == asset.id
    fetched = (await db_session.execute(select(Character).where(Character.id == character.id))).scalars().one()
    assert fetched.canonical_asset_image_id == asset.id

    # Clearing it.
    resp = await client.put(f"/api/characters/{character.id}/canonical-image",
                            json={"asset_image_id": None})
    assert resp.status_code == 200
    assert resp.json()["canonical_asset_image_id"] is None


@pytest.mark.asyncio
async def test_set_canonical_image_missing_asset_404(client, character):
    resp = await client.put(f"/api/characters/{character.id}/canonical-image",
                            json={"asset_image_id": str(uuid.uuid4())})
    assert resp.status_code == 404

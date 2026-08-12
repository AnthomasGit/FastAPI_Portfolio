"""Shared entity primary-image staging, used by scene stills and shot clips.

The rules under test are the ones the shot-clip reference resolver depends on:
a Location's primary image is its PLATE (falling back to its canonical), every
other entity's is its canonical, and anything unusable degrades to None with a
warning rather than raising — one missing reference must not fail a whole
overnight batch.
"""
import os
import uuid

import pytest

from database import Character, Location, Prop, AssetImage
from database import scene_characters, scene_locations, scene_props
import services.job_handlers as jh
from services.job_handlers import (
    primary_asset_image_id,
    stage_entity_primary_image,
    resolve_scene_entities,
)


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    return out_dir, in_dir


async def _asset(db_session, project, out_dir, name, *, on_disk=True):
    rel = f"assets/{project.id}/{name}.png"
    if on_disk:
        os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(b"img")
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="character", status="completed", image_url=rel)
    db_session.add(asset)
    await db_session.flush()
    return asset


# ── which image is "primary" ───────────────────────────────────────────────

def test_location_prefers_plate_over_canonical():
    loc = Location(id="l1", name="Bar", plate_asset_image_id="plate-1",
                   canonical_asset_image_id="canon-1")
    assert primary_asset_image_id(loc, "location") == "plate-1"


def test_location_falls_back_to_canonical_without_plate():
    loc = Location(id="l1", name="Bar", canonical_asset_image_id="canon-1")
    assert primary_asset_image_id(loc, "location") == "canon-1"


def test_character_and_prop_use_canonical():
    assert primary_asset_image_id(
        Character(id="c1", name="Ada", canonical_asset_image_id="canon-c"), "character") == "canon-c"
    assert primary_asset_image_id(
        Prop(id="p1", name="Knife", canonical_asset_image_id="canon-p"), "prop") == "canon-p"


def test_entity_without_any_image_is_none():
    assert primary_asset_image_id(Character(id="c1", name="Ada"), "character") is None


# ── staging ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_copies_into_input_dir(db_session, project, dirs):
    out_dir, in_dir = dirs
    asset = await _asset(db_session, project, out_dir, "ada")
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Ada",
                     canonical_asset_image_id=asset.id)
    db_session.add(char)
    await db_session.commit()

    name = await stage_entity_primary_image(char, "character", db_session)
    # Filename is part of the contract — existing scene tests assert on it.
    assert name == f"{char.id}_canon.png"
    assert os.path.exists(os.path.join(in_dir, name))


@pytest.mark.asyncio
async def test_location_stages_under_plate_suffix(db_session, project, dirs):
    out_dir, _ = dirs
    asset = await _asset(db_session, project, out_dir, "bar")
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar",
                   plate_asset_image_id=asset.id)
    db_session.add(loc)
    await db_session.commit()
    assert await stage_entity_primary_image(loc, "location", db_session) == f"{loc.id}_plate.png"


@pytest.mark.asyncio
async def test_missing_file_on_disk_returns_none(db_session, project, dirs):
    """Degrades, never raises — a batch must survive one absent reference."""
    out_dir, _ = dirs
    asset = await _asset(db_session, project, out_dir, "ghost", on_disk=False)
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Ghost",
                     canonical_asset_image_id=asset.id)
    db_session.add(char)
    await db_session.commit()
    assert await stage_entity_primary_image(char, "character", db_session) is None


@pytest.mark.asyncio
async def test_no_canonical_returns_none(db_session, project, dirs):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Nobody")
    db_session.add(char)
    await db_session.commit()
    assert await stage_entity_primary_image(char, "character", db_session) is None


# ── scene entity ordering ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scene_entities_ordered_characters_locations_props(db_session, project, scene):
    """Identity first: when slots run out the tail is dropped, and losing a
    character's likeness is far more visible than losing a prop."""
    zed = Character(id=str(uuid.uuid4()), project_id=project.id, name="Zed")
    ada = Character(id=str(uuid.uuid4()), project_id=project.id, name="Ada")
    bar = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar")
    knife = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Knife")
    for e in (zed, ada, bar, knife):
        db_session.add(e)
    await db_session.flush()
    await db_session.execute(scene_characters.insert().values(
        [{"scene_id": scene.id, "character_id": zed.id},
         {"scene_id": scene.id, "character_id": ada.id}]))
    await db_session.execute(scene_locations.insert().values(
        scene_id=scene.id, location_id=bar.id))
    await db_session.execute(scene_props.insert().values(
        scene_id=scene.id, prop_id=knife.id))
    await db_session.commit()

    resolved = await resolve_scene_entities(scene.id, db_session)
    assert [t for t, _ in resolved] == ["character", "character", "location", "prop"]
    # characters sorted by name, so Ada precedes Zed
    assert [e.name for _, e in resolved] == ["Ada", "Zed", "Bar", "Knife"]

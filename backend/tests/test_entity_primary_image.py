"""Per-scene primary image resolution.

An asset's reference image is chosen PER SCENE, not once per project: the same
character wears different clothes in different scenes. The source of truth is
`scene_<type>.reference_id`; a scene that hasn't picked inherits the entity's
newest reference, so a scene renders as soon as art exists and picking is only
needed to override.
"""
import os
import uuid

import pytest

from database import (
    AssetImage, Character, Location, Prop, Reference,
    scene_characters, scene_locations, scene_props,
)
import services.job_handlers as jh
from services.job_handlers import (
    scene_primary_reference,
    has_scene_primary,
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


async def _ref(db_session, project, out_dir, entity_type, entity_id, name, *, on_disk=True):
    """A generated-image Reference (lives under COMFY_OUTPUT_DIR, needs staging)."""
    rel = f"assets/{project.id}/{name}.png"
    if on_disk:
        os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(b"img")
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type=entity_type, status="completed", image_url=rel)
    db_session.add(asset)
    await db_session.flush()
    ref = Reference(id=str(uuid.uuid4()), entity_type=entity_type, entity_id=entity_id,
                    role="moodboard", url=rel, asset_image_id=asset.id)
    db_session.add(ref)
    await db_session.flush()
    return ref


async def _character(db_session, project, scene, name="Ada"):
    c = Character(id=str(uuid.uuid4()), project_id=project.id, name=name)
    db_session.add(c)
    await db_session.flush()
    await db_session.execute(scene_characters.insert().values(
        scene_id=scene.id, character_id=c.id))
    await db_session.commit()
    return c


# ── resolution order ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scene_pick_wins_over_newest(db_session, project, scene, dirs):
    """The whole point: a scene overrides the default, e.g. a wardrobe change."""
    out_dir, _ = dirs
    char = await _character(db_session, project, scene)
    old = await _ref(db_session, project, out_dir, "character", char.id, "ada_coat")
    new = await _ref(db_session, project, out_dir, "character", char.id, "ada_dress")
    # This scene explicitly wants the older image.
    await db_session.execute(scene_characters.update().where(
        scene_characters.c.character_id == char.id).values(reference_id=old.id))
    await db_session.commit()

    picked = await scene_primary_reference(scene.id, "character", char.id, db_session)
    assert picked.id == old.id, "explicit scene pick must beat the newest reference"


@pytest.mark.asyncio
async def test_falls_back_to_newest_when_scene_has_not_picked(db_session, project, scene, dirs):
    """So a scene renders as soon as art exists, with no curation required."""
    out_dir, _ = dirs
    char = await _character(db_session, project, scene)
    await _ref(db_session, project, out_dir, "character", char.id, "ada_1")
    newest = await _ref(db_session, project, out_dir, "character", char.id, "ada_2")
    await db_session.commit()

    picked = await scene_primary_reference(scene.id, "character", char.id, db_session)
    assert picked.id == newest.id


@pytest.mark.asyncio
async def test_two_scenes_can_use_different_images(db_session, project, scene, dirs):
    """The wardrobe case, end to end."""
    from database import Scene
    out_dir, _ = dirs
    scene2 = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=2,
                   slugline="S2", screenplay="x", sort_order=1)
    db_session.add(scene2)
    await db_session.flush()
    char = await _character(db_session, project, scene)
    await db_session.execute(scene_characters.insert().values(
        scene_id=scene2.id, character_id=char.id))
    coat = await _ref(db_session, project, out_dir, "character", char.id, "coat")
    dress = await _ref(db_session, project, out_dir, "character", char.id, "dress")
    await db_session.execute(scene_characters.update().where(
        (scene_characters.c.scene_id == scene.id)
        & (scene_characters.c.character_id == char.id)).values(reference_id=coat.id))
    await db_session.execute(scene_characters.update().where(
        (scene_characters.c.scene_id == scene2.id)
        & (scene_characters.c.character_id == char.id)).values(reference_id=dress.id))
    await db_session.commit()

    a = await scene_primary_reference(scene.id, "character", char.id, db_session)
    b = await scene_primary_reference(scene2.id, "character", char.id, db_session)
    assert a.id == coat.id and b.id == dress.id


@pytest.mark.asyncio
async def test_no_references_at_all_is_none(db_session, project, scene, dirs):
    char = await _character(db_session, project, scene)
    assert await scene_primary_reference(scene.id, "character", char.id, db_session) is None
    assert await has_scene_primary(scene.id, "character", char.id, db_session) is False


@pytest.mark.asyncio
async def test_locations_and_props_follow_the_same_rule(db_session, project, scene, dirs):
    """One rule for all three entity types — no special case for locations."""
    out_dir, _ = dirs
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar")
    prop = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Knife")
    db_session.add_all([loc, prop])
    await db_session.flush()
    await db_session.execute(scene_locations.insert().values(
        scene_id=scene.id, location_id=loc.id))
    await db_session.execute(scene_props.insert().values(
        scene_id=scene.id, prop_id=prop.id))
    await _ref(db_session, project, out_dir, "location", loc.id, "bar")
    await _ref(db_session, project, out_dir, "prop", prop.id, "knife")
    await db_session.commit()

    assert await has_scene_primary(scene.id, "location", loc.id, db_session)
    assert await has_scene_primary(scene.id, "prop", prop.id, db_session)


# ── staging ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_copies_generated_image_into_input_dir(db_session, project, scene, dirs):
    out_dir, in_dir = dirs
    char = await _character(db_session, project, scene)
    ref = await _ref(db_session, project, out_dir, "character", char.id, "ada")
    await db_session.commit()

    name = await stage_entity_primary_image(char, "character", db_session, scene_id=scene.id)
    assert name == f"{ref.id}_ref.png"
    assert os.path.exists(os.path.join(in_dir, name))


@pytest.mark.asyncio
async def test_plain_upload_is_used_in_place(db_session, project, scene, dirs):
    """Uploads already live flat in the input dir — no staging copy needed."""
    _out, in_dir = dirs
    char = await _character(db_session, project, scene)
    with open(in_dir / "upload.png", "wb") as f:
        f.write(b"img")
    db_session.add(Reference(id=str(uuid.uuid4()), entity_type="character",
                             entity_id=char.id, role="moodboard", url="upload.png"))
    await db_session.commit()

    assert await stage_entity_primary_image(
        char, "character", db_session, scene_id=scene.id) == "upload.png"


@pytest.mark.asyncio
async def test_missing_file_degrades_to_none(db_session, project, scene, dirs):
    """Degrades, never raises — a batch must survive one absent reference."""
    out_dir, _ = dirs
    char = await _character(db_session, project, scene)
    await _ref(db_session, project, out_dir, "character", char.id, "ghost", on_disk=False)
    await db_session.commit()
    assert await stage_entity_primary_image(
        char, "character", db_session, scene_id=scene.id) is None


# ── scene entity ordering (unchanged) ──────────────────────────────────────

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
    assert [e.name for _, e in resolved] == ["Ada", "Zed", "Bar", "Knife"]


@pytest.mark.asyncio
async def test_ordering_is_case_insensitive(db_session, project, scene):
    """The shot list mirrors this order to show which SLOT each asset occupies,
    and it sorts case-insensitively. Postgres' default collation puts uppercase
    first ("TV" before "couch"), so a case-sensitive order here would make the
    UI display slot numbers that disagree with the ones actually rendered.
    """
    for name in ("TV", "couch", "Remote", "table"):
        p = Prop(id=str(uuid.uuid4()), project_id=project.id, name=name)
        db_session.add(p)
        await db_session.flush()
        await db_session.execute(scene_props.insert().values(
            scene_id=scene.id, prop_id=p.id))
    await db_session.commit()

    names = [e.name for _t, e in await resolve_scene_entities(scene.id, db_session)]
    assert names == ["couch", "Remote", "table", "TV"]

"""Identity base plates (0028): the image a character's/prop's cells edit FROM.

The bug these replace: sheets resolved their source as "the entity's newest
reference", i.e. whatever was generated last — measured, a character sheet
edited a living-room scene still and returned the subject sitting on the sofa in
every cell, because an image-edit model preserves what it is handed.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AssetImage, Character, JobRecord, Prop, Reference
from services import base_plate_service, sheet_service


async def _character(db_session, project, **kw):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero", **kw)
    db_session.add(char)
    await db_session.commit()
    return char


# ── prompt ─────────────────────────────────────────────────────────────────

def test_plate_prompt_keeps_the_default_outfit_and_drops_palette():
    """The plate wears the default outfit ON PURPOSE: every angle cell edits it,
    and a plate already dressed leaves those cells with only a rotation to do —
    the one operation this model does reliably."""
    char = Character(id="c", name="Ada", prompt_profile={
        "appearance": ["mid-40s", "greying beard"],
        "palette": ["olive green"],
        "outfits": [{"name": "day", "items": ["olive jersey"], "default": True},
                    {"name": "gala", "items": ["black gown"]}],
    })
    prompt = base_plate_service.build_plate_prompt(char, "character")
    assert "greying beard" in prompt
    assert "olive jersey" in prompt          # default outfit in
    assert "black gown" not in prompt        # alternates out
    assert "olive green" not in prompt       # palette out
    assert "plain light grey studio backdrop" in prompt


def test_prop_plate_uses_prop_framing():
    """A prop has no 'standing upright' — and the framing must bar the hands and
    surroundings that make an edit source unusable."""
    prompt = base_plate_service.build_plate_prompt(Prop(id="p", name="Knife"), "prop")
    assert "no hands" in prompt
    assert "standing upright" not in prompt


# ── ensure / reuse ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_generates_a_plate_when_missing(db_session, project):
    char = await _character(db_session, project)
    asset_id, job = await base_plate_service.ensure_base_plate(char, "character", db_session)
    await db_session.commit()

    assert job is not None and job.kind == "base_plate"
    assert job.payload["asset_image_id"] == asset_id
    asset = await db_session.get(AssetImage, asset_id)
    assert asset.kind == "base_plate" and asset.status == "queued"


@pytest.mark.asyncio
async def test_ensure_reuses_an_existing_plate(db_session, project):
    char = await _character(db_session, project)
    first_id, _ = await base_plate_service.ensure_base_plate(char, "character", db_session)
    char.base_asset_image_id = first_id
    await db_session.commit()

    again_id, job = await base_plate_service.ensure_base_plate(char, "character", db_session)
    assert again_id == first_id
    assert job is None          # nothing to depend on, nothing to render


@pytest.mark.asyncio
async def test_ensure_regenerates_when_the_pointer_dangles(db_session, project):
    """A plate whose AssetImage was deleted must not be handed to a LoadImage
    node: ComfyUI rejects the ENTIRE graph at validation while still reporting
    the submit as successful."""
    char = await _character(db_session, project, base_asset_image_id="gone")
    asset_id, job = await base_plate_service.ensure_base_plate(char, "character", db_session)
    await db_session.commit()
    assert job is not None and asset_id != "gone"


# ── completion ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completion_points_the_entity_at_the_plate(db_session, project):
    char = await _character(db_session, project)
    asset_id, job = await base_plate_service.ensure_base_plate(char, "character", db_session)
    await db_session.commit()

    await base_plate_service.on_complete_base_plate(
        {**job.payload, "image_url": "plate.png"}, {}, db_session)

    await db_session.refresh(char)
    assert char.base_asset_image_id == asset_id
    asset = await db_session.get(AssetImage, asset_id)
    assert asset.status == "completed" and asset.image_url == "plate.png"


@pytest.mark.asyncio
async def test_completion_publishes_no_reference(db_session, project):
    """A plate is a working source, not a look. Publishing it would make it the
    entity's newest reference and silently become every scene's inherited
    image."""
    char = await _character(db_session, project)
    _, job = await base_plate_service.ensure_base_plate(char, "character", db_session)
    await db_session.commit()

    await base_plate_service.on_complete_base_plate(
        {**job.payload, "image_url": "plate.png"}, {}, db_session)

    refs = (await db_session.execute(
        select(Reference).where(Reference.entity_id == char.id)
    )).scalars().all()
    assert refs == []


# ── wiring into a sheet ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_sheet_reuses_the_plate_instead_of_making_another(
        db_session, project):
    char = await _character(db_session, project)
    _, jobs = await sheet_service.create_character_sheet(char, db_session)
    plate = next(j for j in jobs if j.kind == "base_plate")

    # Simulate the plate finishing, then run a second sheet.
    await base_plate_service.on_complete_base_plate(
        {**plate.payload, "image_url": "plate.png"}, {}, db_session)
    _, jobs2 = await sheet_service.create_character_sheet(char, db_session)

    assert not any(j.kind == "base_plate" for j in jobs2)
    cells = [j for j in jobs2 if j.kind == "character_sheet"]
    assert cells and all(
        j.payload["source_asset_image_id"] == plate.payload["asset_image_id"]
        for j in cells)
    # Nothing to wait for, so the cells are immediately claimable.
    assert all(j.depends_on_job_id is None for j in cells)

"""KAN-32 — prompt_profile / style_profile / canonical_asset_image_id columns."""
import uuid

import pytest
from sqlalchemy import select

from database import Character, Location, Prop, Project, AssetImage


@pytest.mark.asyncio
async def test_prompt_profile_round_trips(db_session, project):
    profile = {
        "appearance": ["tall", "grey beard", "scar over left eye"],
        "wardrobe": ["worn leather coat"],
        "palette": ["muted earth tones"],
        "negative": ["modern clothing", "text"],
        "locked_seed": 424242,
        "notes": "keep the scar consistent",
    }
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Aldous",
                     prompt_profile=profile)
    db_session.add(char)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Character).where(Character.id == char.id))
    ).scalars().one()
    assert fetched.prompt_profile == profile
    assert fetched.prompt_profile["locked_seed"] == 424242
    assert fetched.canonical_asset_image_id is None


@pytest.mark.asyncio
async def test_style_profile_round_trips(db_session, project):
    style = {"film_stock": "Kodak Vision3 500T", "lens": "35mm anamorphic",
             "grade": "teal-orange", "lighting": "low-key", "extra": ["film grain"]}
    project.style_profile = style
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Project).where(Project.id == project.id))
    ).scalars().one()
    assert fetched.style_profile == style


@pytest.mark.asyncio
async def test_canonical_asset_image_fk(db_session, project):
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="character", kind="txt2img", status="completed",
                       image_url="assets/x/characters/hero_00001_.png")
    db_session.add(asset)
    await db_session.flush()

    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="The Keep",
                   canonical_asset_image_id=asset.id)
    prop = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Lantern",
                prompt_profile={"appearance": ["brass", "dented"]})
    db_session.add_all([loc, prop])
    await db_session.commit()

    assert (await db_session.get(Location, loc.id)).canonical_asset_image_id == asset.id
    assert (await db_session.get(Prop, prop.id)).prompt_profile["appearance"] == ["brass", "dented"]

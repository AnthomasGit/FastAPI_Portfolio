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



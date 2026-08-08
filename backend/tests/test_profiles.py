"""KAN-33 — LLM prompt/style profile generation + edit endpoints."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from database import Character, Project


def _fake_completion(content: str):
    """A stand-in for the OpenAI client's chat completion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


CLEAN_JSON = (
    '{"appearance": ["tall", "grey beard"], "wardrobe": ["leather coat"], '
    '"palette": ["earth tones"], "negative": ["text"], "locked_seed": 7, "notes": "keep scar"}'
)
FENCED_JSON = "```json\n" + CLEAN_JSON + "\n```"


@pytest.mark.asyncio
async def test_generate_prompt_profile_clean_json(client, db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Aldous",
                     description="a weathered ranger")
    db_session.add(char)
    await db_session.commit()

    with patch("services.ai_service.client.chat.completions.create",
               new=AsyncMock(return_value=_fake_completion(CLEAN_JSON))):
        resp = await client.post(f"/api/characters/{char.id}/prompt-profile")
    assert resp.status_code == 200
    prof = resp.json()["prompt_profile"]
    assert prof["appearance"] == ["tall", "grey beard"]
    assert prof["locked_seed"] == 7

    # Persisted on the row.
    fetched = (await db_session.execute(select(Character).where(Character.id == char.id))).scalars().one()
    assert fetched.prompt_profile["notes"] == "keep scar"


@pytest.mark.asyncio
async def test_generate_prompt_profile_markdown_fenced(client, db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Mara")
    db_session.add(char)
    await db_session.commit()

    with patch("services.ai_service.client.chat.completions.create",
               new=AsyncMock(return_value=_fake_completion(FENCED_JSON))):
        resp = await client.post(f"/api/characters/{char.id}/prompt-profile")
    assert resp.status_code == 200
    # extract_json strips the markdown fence.
    assert resp.json()["prompt_profile"]["wardrobe"] == ["leather coat"]


@pytest.mark.asyncio
async def test_generate_style_profile(client, db_session, project):
    style = '{"film_stock": "Vision3 500T", "lens": "35mm", "grade": "teal-orange", "lighting": "low-key", "extra": ["grain"]}'
    with patch("services.ai_service.client.chat.completions.create",
               new=AsyncMock(return_value=_fake_completion(style))):
        resp = await client.post(f"/api/projects/{project.id}/style-profile")
    assert resp.status_code == 200
    assert resp.json()["style_profile"]["grade"] == "teal-orange"
    fetched = (await db_session.execute(select(Project).where(Project.id == project.id))).scalars().one()
    assert fetched.style_profile["film_stock"] == "Vision3 500T"


@pytest.mark.asyncio
async def test_put_persists_user_edit_unchanged(client, db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Aldous")
    db_session.add(char)
    await db_session.commit()

    edit = {
        "appearance": ["exactly what the user typed"],
        "wardrobe": [], "palette": ["#123456"], "negative": [],
        "locked_seed": 999, "notes": "user override", "custom_extra_key": "kept",
    }
    resp = await client.put(f"/api/characters/{char.id}/prompt-profile", json=edit)
    assert resp.status_code == 200
    assert resp.json()["prompt_profile"] == edit

    # Stored verbatim, including the non-schema key — the user's edit wins.
    fetched = (await db_session.execute(select(Character).where(Character.id == char.id))).scalars().one()
    assert fetched.prompt_profile == edit


@pytest.mark.asyncio
async def test_invalid_entity_type_404(client):
    resp = await client.post(f"/api/scenes/{uuid.uuid4()}/prompt-profile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_missing_entity_404(client):
    resp = await client.post(f"/api/characters/{uuid.uuid4()}/prompt-profile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_location_profile_uses_location_schema(client, db_session, project):
    """A location's prompt-profile generation asks for environment-shaped keys,
    not the character wardrobe/face ones (KAN-41)."""
    from database import Location
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Throne Room",
                   description="a cold gothic hall")
    db_session.add(loc)
    await db_session.commit()

    mock = AsyncMock(return_value=_fake_completion(
        '{"environment": ["gothic stone hall"], "architecture": ["vaulted ceiling"], '
        '"materials": ["flagstone"], "lighting": ["torchlight"], "palette": ["cold blue"], '
        '"negative": ["people"], "locked_seed": null, "notes": ""}'))
    with patch("services.ai_service.client.chat.completions.create", new=mock):
        resp = await client.post(f"/api/locations/{loc.id}/prompt-profile")
    assert resp.status_code == 200
    assert resp.json()["prompt_profile"]["environment"] == ["gothic stone hall"]
    # The system prompt sent to the LLM must request location-specific keys.
    system_msg = mock.await_args.kwargs["messages"][0]["content"].lower()
    assert "environment" in system_msg and "architecture" in system_msg
    assert "wardrobe" not in system_msg

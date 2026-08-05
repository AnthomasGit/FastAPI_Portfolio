"""KAN-34 — profile-based prompt composition."""
import uuid
from types import SimpleNamespace

import pytest

from services.prompt_builder import build_prompt, build_scene_prompt, LEGACY_STYLE_TAIL


def _scene(slug="INT. KEEP - NIGHT", screenplay="Aldous enters."):
    return SimpleNamespace(slugline=slug, screenplay=screenplay)


def _ent(name, description=None, prompt_profile=None):
    return SimpleNamespace(name=name, description=description, prompt_profile=prompt_profile)


def test_deterministic_byte_identical():
    scene = _scene()
    chars = [
        _ent("Bex", prompt_profile={"appearance": ["short", "red hair"], "negative": ["blur"]}),
        _ent("Aldous", prompt_profile={"appearance": ["tall", "grey beard"], "negative": ["text"]}),
    ]
    project = SimpleNamespace(style_profile={"film_stock": "500T", "extra": ["grain"]})

    a = build_prompt(scene, chars, [], [], project)
    b = build_prompt(scene, list(reversed(chars)), [], [], project)
    # Same inputs (order-independent) -> identical output, both positive+negative.
    assert a == b
    # Characters sorted by name: Aldous before Bex.
    assert a[0].index("Aldous") < a[0].index("Bex")


def test_no_profile_falls_back_to_description_and_keeps_name():
    scene = _scene()
    c = _ent("Nameless Ranger", description="a weathered scout")
    positive, _neg = build_prompt(scene, [c], [], [], None)
    assert "Nameless Ranger" in positive
    assert "a weathered scout" in positive
    # No profile/style -> legacy style tail.
    assert LEGACY_STYLE_TAIL in positive


def test_name_only_when_no_profile_no_description():
    scene = _scene()
    c = _ent("Ghost")
    positive, _neg = build_prompt(scene, [c], [], [], None)
    assert "Ghost" in positive


def test_negatives_separate_and_absent_from_positive():
    scene = _scene()
    chars = [
        _ent("Aldous", prompt_profile={"appearance": ["tall"], "negative": ["text", "watermark"]}),
        _ent("Bex", prompt_profile={"appearance": ["short"], "negative": ["text", "blur"]}),
    ]
    positive, negative = build_prompt(scene, chars, [], [], None)
    # Deduped, first-seen order across sorted entities (Aldous then Bex).
    assert negative == "text, watermark, blur"
    for tok in ("text", "watermark", "blur"):
        assert tok not in positive


def test_style_profile_replaces_legacy_tail():
    scene = _scene()
    project = SimpleNamespace(style_profile={
        "film_stock": "Vision3 500T", "lens": "35mm", "grade": "teal-orange",
        "lighting": "low-key", "extra": ["film grain", "halation"],
    })
    positive, _neg = build_prompt(scene, [], [], [], project)
    assert "Vision3 500T, 35mm, teal-orange, low-key, film grain, halation" in positive
    assert LEGACY_STYLE_TAIL not in positive


# ── integration through the DB loader ──────────────────────────────────────

@pytest.mark.asyncio
async def test_build_scene_prompt_and_construct_prompt_delegate(db_session, project, scene, character):
    from database import scene_characters
    character.prompt_profile = {"appearance": ["tall"], "negative": ["blurry"]}
    await db_session.execute(
        scene_characters.insert().values(scene_id=scene.id, character_id=character.id)
    )
    await db_session.commit()

    positive, negative = await build_scene_prompt(scene.id, db_session)
    assert character.name in positive
    assert negative == "blurry"

    # construct_prompt returns just the positive (signature preserved).
    from services.comfyui_service import construct_prompt
    assert await construct_prompt(scene.id, db_session) == positive

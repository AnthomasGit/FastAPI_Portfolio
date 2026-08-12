"""Picker labels for references.

Every generated image carries role="moodboard", so labelling by role renders a
picker as "moodboard, moodboard (1), moodboard (2)…" — useless exactly where it
matters most: choosing which look a scene uses.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from database import AssetImage, Character, Reference
from schemas.schemas import reference_label


def _ref(*, params=None, prompt=None, has_asset=True, role="moodboard",
         created=datetime(2026, 7, 27)):
    asset = SimpleNamespace(params=params, prompt=prompt) if has_asset else None
    return SimpleNamespace(asset_image=asset, role=role, created_at=created)


# ── layer 1: the sheet/angle slot ──────────────────────────────────────────

def test_sheet_slot_wins():
    assert reference_label(_ref(params={"sheet_slot": "profile"}, prompt="ignored")) == "profile"


def test_angle_slot_used_for_plates():
    assert reference_label(_ref(params={"angle_slot": "left45"})) == "left45"


def test_group_prefix_is_stripped():
    """"red coat" beats "wardrobe:red coat" in a narrow trigger, and the group
    is obvious from context. This is the wardrobe case."""
    assert reference_label(_ref(params={"sheet_slot": "wardrobe:red coat"})) == "red coat"
    assert reference_label(_ref(params={"sheet_slot": "materials:brushed brass"})) == "brushed brass"


def test_expression_slots_pass_through():
    assert reference_label(_ref(params={"sheet_slot": "expr-joy"})) == "expr-joy"


# ── layer 2: a prompt excerpt ──────────────────────────────────────────────

def test_falls_back_to_prompt_excerpt():
    label = reference_label(_ref(params={}, prompt="late 20s male with a beard and dark square glasses"))
    assert label.endswith("…") and len(label) <= 30
    assert label.startswith("late 20s male")


def test_short_prompt_is_not_truncated():
    assert reference_label(_ref(params={}, prompt="A man on a couch")) == "A man on a couch"


def test_excerpt_breaks_on_a_word_boundary():
    label = reference_label(_ref(params={}, prompt="aaa bbb ccc ddd eee fff ggg hhh iii"))
    assert " …" not in label and not label[:-1].endswith(" ")


# ── layer 3: uploads with neither ──────────────────────────────────────────

def test_plain_upload_gets_role_and_date():
    """A hand-uploaded reference has no asset image at all."""
    assert reference_label(_ref(has_asset=False)) == "moodboard · Jul 27"


def test_asset_without_params_or_prompt_still_labels():
    assert reference_label(_ref(params=None, prompt=None)) == "moodboard · Jul 27"


# ── served on the API ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoint_serves_distinguishable_labels(client, db_session, project):
    """The point of the whole change: two references on one entity must not
    both read "moodboard"."""
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Wife")
    db_session.add(char)
    await db_session.flush()

    sheet_asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                             entity_type="character", kind="sheet", status="completed",
                             image_url="a.png", prompt="Wife, full body",
                             params={"sheet_slot": "wardrobe:pyjamas"})
    adhoc_asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                             entity_type="character", kind="txt2img", status="completed",
                             image_url="b.png",
                             prompt="A white woman with short blonde hair in a lab coat")
    db_session.add_all([sheet_asset, adhoc_asset])
    await db_session.flush()
    for a in (sheet_asset, adhoc_asset):
        db_session.add(Reference(id=str(uuid.uuid4()), entity_type="character",
                                 entity_id=char.id, role="moodboard",
                                 url=a.image_url, asset_image_id=a.id))
    await db_session.commit()

    refs = (await client.get(f"/api/characters/{char.id}/references")).json()
    labels = {r["label"] for r in refs}
    assert labels == {"pyjamas", "A white woman with short…"}
    assert len(labels) == 2, "labels must distinguish, not repeat the role"

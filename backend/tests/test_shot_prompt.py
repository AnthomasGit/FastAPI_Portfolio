"""H3 full-reference prompt composition (backend/reference/h3_full_reference_guide.md).

The invariant these tests protect: reference slot N == image{N} in the graph ==
<Subject N> in the prompt. If the subject numbering and the injected slot order
ever diverge, the prompt describes the wrong picture and the failure is silent.
"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from database import Character, Location, Prop, Shot, scene_characters, scene_locations, scene_props
from services import shot_prompt_service as sps
from services.job_handlers import select_shot_entities


def _llm_json(payload: dict):
    """Fake an OpenAI chat completion returning `payload` as JSON."""
    msg = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


SIX = {k: f"{k} body" for k in sps.SECTIONS}


# ── guide vocabulary ───────────────────────────────────────────────────────

def test_task_type_prefix_varies_with_audio_role():
    """The guide picks a different task type per audio relationship — copying
    the signal is 'audio reuse', referencing only its timbre is 'audio reference'."""
    assert sps.task_type_prefix(None) == "[reference generation]"
    assert sps.task_type_prefix("dialogue") == "[reference generation + audio reuse]"
    assert sps.task_type_prefix("timbre") == "[reference generation + audio reference]"


def test_audio_markers_match_the_guide():
    assert sps.AUDIO_ROLES["dialogue"]["marker"] == "fully_copy"
    assert sps.AUDIO_ROLES["timbre"]["marker"] == "reference"


def test_timbre_role_forbids_carrying_source_dialogue():
    """Guide: when only timbre is referenced, the original dialogue must NOT be
    carried into the target video."""
    assert "do not carry" in sps.AUDIO_ROLES["timbre"]["dialogue_rule"].lower()


def test_subject_labels_are_one_based():
    assert sps.subject_label(0) == "<Subject 1>"
    assert sps.subject_label(8) == "<Subject 9>"


# ── document round-trip ────────────────────────────────────────────────────

def test_render_document_emits_all_six_sections_in_order():
    doc = sps.render_document(SIX)
    positions = [doc.index(f"{name}:") for name in sps.SECTIONS]
    assert positions == sorted(positions)


def test_missing_section_renders_as_na():
    doc = sps.render_document({"summary": "s"})
    assert "non_diegetic_music:\nN/A" in doc


def test_parse_document_round_trips():
    assert sps.parse_document(sps.render_document(SIX)) == SIX


# ── subject brief numbering ────────────────────────────────────────────────

def test_subject_brief_numbers_match_slot_order():
    entities = [
        ("character", Character(id="c1", name="Ada")),
        ("location", Location(id="l1", name="Bar")),
        ("prop", Prop(id="p1", name="Knife")),
    ]
    brief = sps.build_subject_brief(entities)
    assert [b["label"] for b in brief] == ["<Subject 1>", "<Subject 2>", "<Subject 3>"]
    assert [b["slot"] for b in brief] == [1, 2, 3]
    assert [b["name"] for b in brief] == ["Ada", "Bar", "Knife"]


# ── composition ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compose_returns_rendered_document():
    shot = Shot(id="s1", scene_id="sc1", shot_number="1A", shot_size="CU",
                movement="Static", description="She turns.")
    scene = SimpleNamespace(slugline="INT. BAR", screenplay="ADA: Hello.")
    with patch.object(sps.ai_service.client.chat.completions, "create",
                      new=AsyncMock(return_value=_llm_json(SIX))):
        doc = await sps.compose_shot_clip_prompt(
            shot, scene, [("character", Character(id="c1", name="Ada"))], None)
    assert "subject_definitions:" in doc
    assert "detailed_description:" in doc


@pytest.mark.asyncio
async def test_compose_passes_labels_and_prefix_to_the_model():
    """The model must be handed the exact labels and task-type prefix — it is
    told not to renumber them, so they have to be in the prompt."""
    shot = Shot(id="s1", scene_id="sc1", shot_number="1A", audio_role="timbre")
    scene = SimpleNamespace(slugline="INT. BAR", screenplay="")
    create = AsyncMock(return_value=_llm_json(SIX))
    with patch.object(sps.ai_service.client.chat.completions, "create", new=create):
        await sps.compose_shot_clip_prompt(
            shot, scene,
            [("character", Character(id="c1", name="Ada")),
             ("location", Location(id="l1", name="Bar"))],
            None, has_audio=True)

    sent = " ".join(m["content"] for m in create.call_args.kwargs["messages"])
    assert "<Subject 1>" in sent and "<Subject 2>" in sent
    assert "[reference generation + audio reference]" in sent
    assert "fully_copy" not in sent          # wrong marker for the timbre role
    assert "reference" in sent


@pytest.mark.asyncio
async def test_single_shot_instruction_has_no_timestamp():
    """One clip == one shot, so the description is a single [Shot 1] with no cut time."""
    sys_prompt = sps._system_prompt(None, has_audio=False)
    assert "[Shot 1]" in sys_prompt
    assert "NO timestamp" in sys_prompt


# ── persistence + idempotence ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compose_for_shot_persists_and_is_idempotent(db_session, project, scene):
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add(shot)
    await db_session.commit()

    create = AsyncMock(return_value=_llm_json(SIX))
    with patch.object(sps.ai_service.client.chat.completions, "create", new=create):
        await sps.compose_for_shot(shot, db_session)
        assert create.await_count == 1
        # Second call must reuse the stored (user-editable) prompt.
        await sps.compose_for_shot(shot, db_session)
        assert create.await_count == 1

    await db_session.refresh(shot)
    assert shot.clip_prompt.startswith("subject_definitions:")


@pytest.mark.asyncio
async def test_force_recomposes(db_session, project, scene):
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, clip_prompt="old")
    db_session.add(shot)
    await db_session.commit()

    create = AsyncMock(return_value=_llm_json(SIX))
    with patch.object(sps.ai_service.client.chat.completions, "create", new=create):
        await sps.compose_for_shot(shot, db_session, force=True)
    assert create.await_count == 1
    await db_session.refresh(shot)
    assert shot.clip_prompt != "old"


@pytest.mark.asyncio
async def test_endpoint_composes(client, db_session, scene):
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add(shot)
    await db_session.commit()
    with patch.object(sps.ai_service.client.chat.completions, "create",
                      new=AsyncMock(return_value=_llm_json(SIX))):
        r = await client.post(f"/api/shots/{shot.id}/compose-prompt")
    assert r.status_code == 200
    assert r.json()["clip_prompt"].startswith("subject_definitions:")


@pytest.mark.asyncio
async def test_endpoint_404_for_missing_shot(client):
    r = await client.post(f"/api/shots/{uuid.uuid4()}/compose-prompt")
    assert r.status_code == 404


# ── clip_refs override drives subject selection AND order ──────────────────

@pytest.mark.asyncio
async def test_override_reorders_subjects(db_session, project, scene):
    ada = Character(id=str(uuid.uuid4()), project_id=project.id, name="Ada")
    zed = Character(id=str(uuid.uuid4()), project_id=project.id, name="Zed")
    bar = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar")
    for e in (ada, zed, bar):
        db_session.add(e)
    await db_session.flush()
    await db_session.execute(scene_characters.insert().values(
        [{"scene_id": scene.id, "character_id": ada.id},
         {"scene_id": scene.id, "character_id": zed.id}]))
    await db_session.execute(scene_locations.insert().values(
        scene_id=scene.id, location_id=bar.id))
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, clip_refs=[
        {"entity_type": "location", "entity_id": bar.id},
        {"entity_type": "character", "entity_id": zed.id},
    ])
    db_session.add(shot)
    await db_session.commit()

    from services.job_handlers import resolve_scene_entities
    default = await resolve_scene_entities(scene.id, db_session)
    assert [e.name for _, e in default] == ["Ada", "Zed", "Bar"]

    picked = await select_shot_entities(shot, default, db_session)
    assert [e.name for _, e in picked] == ["Bar", "Zed"]
    # …and the subject numbering follows the override, not the scene default.
    assert [b["name"] for b in sps.build_subject_brief(picked)] == ["Bar", "Zed"]


@pytest.mark.asyncio
async def test_override_skips_dangling_entity(db_session, project, scene):
    """clip_refs has no FK, so a deleted entity leaves a dangling pin. It must
    be skipped, not raise — a stale pin cannot be allowed to fail the render."""
    ada = Character(id=str(uuid.uuid4()), project_id=project.id, name="Ada")
    db_session.add(ada)
    await db_session.flush()
    await db_session.execute(scene_characters.insert().values(
        scene_id=scene.id, character_id=ada.id))
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, clip_refs=[
        {"entity_type": "character", "entity_id": ada.id},
        {"entity_type": "character", "entity_id": str(uuid.uuid4())},  # gone
    ])
    db_session.add(shot)
    await db_session.commit()

    picked = await select_shot_entities(shot, [("character", ada)], db_session)
    assert [e.name for _, e in picked] == ["Ada"]


@pytest.mark.asyncio
async def test_null_override_uses_scene_default_and_empty_means_none(db_session, scene):
    ada = Character(id="c-ada", name="Ada")
    default = [("character", ada)]
    assert await select_shot_entities(
        Shot(id="s", scene_id=scene.id, clip_refs=None), default, db_session) == default
    assert await select_shot_entities(
        Shot(id="s", scene_id=scene.id, clip_refs=[]), default, db_session) == []

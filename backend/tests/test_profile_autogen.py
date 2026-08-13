"""Auto-generated prompt_profiles.

Without a profile, entity_prompt falls back to the screenplay description —
narrative, not visual ("Anxiously watches the game"), pinning no identity — and
does so SILENTLY. That silence is what made the failure expensive: a character's
jersey rendered olive, then teal, then grey across three runs before anyone
looked at why.
"""
import uuid

import pytest
from sqlalchemy import select

from database import Character, JobRecord, Location, Prop
from services import profile_service, sheet_service

PROFILE = {"appearance": ["mid-40s man", "greying beard"],
           "outfits": [{"name": "day", "items": ["olive jersey"], "default": True}]}

# Captured at import, before conftest's autouse stub patches the module attribute.
_REAL_ENSURE = profile_service.ensure_prompt_profile


@pytest.fixture
def real_ensure(monkeypatch):
    """Undo conftest's autouse stub for the tests that ARE about generation."""
    monkeypatch.setattr("services.profile_service.ensure_prompt_profile", _REAL_ENSURE)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    async def _generate(*, entity_type, name, description=None, style_profile=None):
        calls.append({"entity_type": entity_type, "name": name})
        return dict(PROFILE)

    monkeypatch.setattr("services.ai_service.generate_prompt_profile", _generate)
    return calls


# ── has_profile ────────────────────────────────────────────────────────────

def test_profile_of_only_metadata_counts_as_missing():
    """`notes` and `locked_seed` describe nothing visual, so a profile holding
    only those must still be filled in."""
    assert not profile_service.has_profile(
        Character(id="c", name="A", prompt_profile={"locked_seed": 1, "notes": "hi"}))
    assert not profile_service.has_profile(Character(id="c", name="A", prompt_profile={}))
    assert not profile_service.has_profile(Character(id="c", name="A"))
    assert profile_service.has_profile(Character(id="c", name="A", prompt_profile=PROFILE))
    # Locations carry environment-shaped keys, not appearance/outfits.
    assert profile_service.has_profile(
        Location(id="l", name="Bar", prompt_profile={"environment": ["dim bar"]}))


# ── ensure ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_generates_and_attaches(db_session, project, real_ensure, fake_llm):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     description="A tall man.")
    db_session.add(char)
    await db_session.commit()

    profile = await profile_service.ensure_prompt_profile(char, "character", db_session)
    assert profile == PROFILE
    assert char.prompt_profile == PROFILE
    assert fake_llm == [{"entity_type": "character", "name": "Hero"}]


@pytest.mark.asyncio
async def test_ensure_never_overwrites_an_existing_profile(
        db_session, project, real_ensure, fake_llm):
    """A user's edit is persisted verbatim by PUT and must survive any later
    auto-fill."""
    mine = {"appearance": ["hand written"]}
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     prompt_profile=mine)
    db_session.add(char)
    await db_session.commit()

    assert await profile_service.ensure_prompt_profile(char, "character", db_session) == mine
    assert fake_llm == []          # no call at all


@pytest.mark.asyncio
async def test_ensure_survives_a_dead_llm(db_session, project, real_ensure, monkeypatch):
    """A profile that cannot be generated must not fail the batch that asked —
    the description fallback stays in place instead."""
    async def _boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("services.ai_service.generate_prompt_profile", _boom)
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()

    assert await profile_service.ensure_prompt_profile(char, "character", db_session) is None
    assert char.prompt_profile is None


# ── project build ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_covers_every_type_and_skips_the_profiled(db_session, project):
    db_session.add_all([
        Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero"),
        Character(id=str(uuid.uuid4()), project_id=project.id, name="Done",
                  prompt_profile=PROFILE),                      # skipped
        Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar"),
        Prop(id=str(uuid.uuid4()), project_id=project.id, name="Knife"),
    ])
    await db_session.commit()

    jobs = await profile_service.enqueue_profile_jobs(project.id, db_session)
    await db_session.commit()

    assert {j.entity_type for j in jobs} == {"character", "location", "prop"}
    assert len(jobs) == 3
    assert all(j.kind == "prompt_profile" and j.status == "queued" for j in jobs)


@pytest.mark.asyncio
async def test_storyboard_save_enqueues_profile_jobs(db_session, project):
    """The good path: profiles are requested at project build, so nothing has to
    discover a missing one later."""
    from services.storyboard_generator import save_storyboard

    await save_storyboard(db_session, project.id, {
        "title": "T", "story_summary": "s",
        "scenes": [{
            "scene_number": 1, "slugline": "INT. BAR", "screenplay": "...",
            "characters": [{"name": "Hero", "description": "tall"}],
            "locations": [{"name": "Bar", "description": "dim"}],
            "props": [{"name": "Knife", "description": "sharp"}],
        }],
    })

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.kind == "prompt_profile")
    )).scalars().all()
    assert {j.entity_type for j in jobs} == {"character", "location", "prop"}


@pytest.mark.asyncio
async def test_local_handler_generates_one(db_session, project, real_ensure, fake_llm):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()

    out = await profile_service.run_prompt_profile(
        {"project_id": project.id, "entity_type": "character", "entity_id": char.id},
        db_session)

    assert out == {"generated": True}
    await db_session.refresh(char)
    assert char.prompt_profile == PROFILE


@pytest.mark.asyncio
async def test_local_handler_tolerates_a_deleted_entity(db_session, project):
    """The job outlives its entity if the user deletes a character while the
    queue is draining; it must no-op rather than fail and burn retries."""
    out = await profile_service.run_prompt_profile(
        {"project_id": project.id, "entity_type": "character", "entity_id": "gone"},
        db_session)
    assert out == {"skipped": "entity gone"}


# ── the safety net ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sheet_fills_a_missing_profile_before_composing(
        db_session, project, real_ensure, fake_llm):
    """A sheet on an unprofiled character must not compose from its description."""
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     description="Anxiously watches the game.")
    db_session.add(char)
    await db_session.commit()

    _, jobs = await sheet_service.create_character_sheet(char, db_session)

    front = next(j for j in jobs if j.payload.get("sheet_slot") == "front")
    assert "greying beard" in front.payload["prompt"]
    assert "Anxiously watches" not in front.payload["prompt"]

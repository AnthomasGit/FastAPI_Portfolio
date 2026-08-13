"""Making sure every entity HAS a prompt_profile.

A profile is the entity's fixed visual tokens. Without one, `entity_prompt`
falls back to the screenplay description — which is narrative, not visual
("Anxiously watches the game"), pins no identity, and leaves every unspecified
attribute free to resample per generation. Measured: a character sheet whose
subject's jersey came out olive, then teal, then grey across three runs, and an
expression cell fighting a base line that said he was anxious.

That fallback is silent, which is what made it expensive to find. Two ways in:

- **at project build** (the good path) — one local job per entity, enqueued once
  the storyboard is saved. Non-blocking, retried, visible in the queue.
- **lazily** (the safety net) — `ensure_prompt_profile` before anything composes
  a prompt, for entities added by hand or created before this existed.

Never fatal: a profile that cannot be generated logs and returns None, leaving
the old description fallback in place. A dead LLM should not fail a batch.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Character, Location, Prop, Project, JobRecord
from services import ai_service
from services.job_handlers import register_local

logger = logging.getLogger("profile_service")

ENTITY_MODELS = {"character": Character, "location": Location, "prop": Prop}

# ── appearance sanitiser ───────────────────────────────────────────────────
# `appearance` is the strictest field in the schema: every token in it is
# repeated in EVERY frame the subject appears in, because _entity_tokens
# composes from it unconditionally. A mood token there is the same failure as
# the screenplay-description fallback, just laundered through the LLM into a
# field we trust — measured: the 14B returned "uninterested expression" for a
# character despite being told to exclude mood.
#
# Abstract state nouns only. "furrowed brow" and "heavy-lidded eyes" are
# legitimate FIXED features and must survive, so this deliberately under-filters
# rather than risk stripping real identity. Suspect tokens are MOVED to `notes`,
# never dropped: nothing consumes `notes`, so it is a safe quarantine the user
# can inspect and correct.
_MOOD_HEADS = ("expression", "demeanor", "demeanour", "mood", "attitude",
               "vibe", "aura", "energy", "disposition")

# Present participles that describe an ACTION rather than a standing state.
# "watching", "clutching" belong to one scene; "greying", "receding" are
# permanent, so a blanket -ing rule would be wrong.
_ACTION_WORDS = ("watching", "holding", "clutching", "carrying", "wearing",
                 "looking", "staring", "gazing", "sitting", "standing",
                 "walking", "running", "reading", "smiling", "frowning",
                 "shouting", "waiting", "focused", "focusing")


def _is_narrative(token: str) -> bool:
    """True for a token describing mood or momentary action rather than a fixed
    physical attribute."""
    words = token.lower().replace("-", " ").split()
    if not words:
        return False
    if words[-1] in _MOOD_HEADS:
        return True
    return any(w in _ACTION_WORDS for w in words)


def sanitize_profile(profile: dict) -> tuple[dict, list[str]]:
    """Move narrative tokens out of `appearance` into `notes`.

    Returns (profile, moved). Applied to GENERATED profiles only — a user's PUT
    is persisted verbatim and is authoritative, so it is never rewritten.
    """
    appearance = [t for t in (profile.get("appearance") or []) if t]
    if not appearance:
        return profile, []
    kept = [t for t in appearance if not _is_narrative(t)]
    moved = [t for t in appearance if _is_narrative(t)]
    if not moved:
        return profile, []
    # Never empty the field entirely: if EVERY token looked narrative the filter
    # is more likely wrong than the model, and an empty appearance would drop
    # the subject back to the description fallback.
    if not kept:
        logger.warning("appearance looked entirely narrative (%s) — left as-is", moved)
        return profile, []
    note = "; ".join(["moved from appearance (narrative/mood)"] + moved)
    profile = {**profile, "appearance": kept,
               "notes": f"{profile.get('notes') or ''} | {note}".strip(" |")}
    return profile, moved

# The keys that carry actual visual content. A profile holding only `notes` or
# `locked_seed` describes nothing, so it counts as missing.
_CONTENT_KEYS = ("appearance", "outfits", "wardrobe", "palette",
                 "environment", "architecture", "materials", "lighting")


def has_profile(entity) -> bool:
    """True when the entity's profile carries at least one visual token."""
    profile = getattr(entity, "prompt_profile", None) or {}
    return any(profile.get(key) for key in _CONTENT_KEYS)


async def ensure_prompt_profile(entity, entity_type: str, db: AsyncSession) -> dict | None:
    """Generate and attach a profile if the entity has none. Returns it, or None
    when one could not be generated.

    Does NOT commit — callers run inside their own transaction (build_sheet_jobs
    is explicitly forbidden from committing, since create_batch flushes its
    Batch row first and a nested commit would persist a half-built batch).
    """
    if has_profile(entity):
        return entity.prompt_profile
    project = await db.get(Project, entity.project_id)
    try:
        profile = await ai_service.generate_prompt_profile(
            entity_type=entity_type,
            name=entity.name,
            description=entity.description,
            style_profile=project.style_profile if project else None,
        )
    except Exception as e:  # noqa: BLE001 - never let this fail a batch
        logger.warning("profile generation failed for %s %s: %s",
                       entity_type, entity.id, e)
        return None
    if not profile:
        return None
    profile, moved = sanitize_profile(profile)
    if moved:
        logger.info("quarantined narrative tokens from %s %s appearance: %s",
                    entity_type, entity.id, moved)
    entity.prompt_profile = profile
    await db.flush()
    return profile


# ── project build ──────────────────────────────────────────────────────────

async def enqueue_profile_jobs(project_id: str, db: AsyncSession) -> list[JobRecord]:
    """One `prompt_profile` job per entity of a project that lacks one.

    Enqueued rather than awaited inline: a project can carry twenty-odd entities
    and the storyboard generator already runs inside an HTTP request. Does not
    commit.
    """
    jobs: list[JobRecord] = []
    for entity_type, model in ENTITY_MODELS.items():
        entities = (await db.execute(
            select(model).where(model.project_id == project_id)
        )).scalars().all()
        for entity in entities:
            if has_profile(entity):
                continue
            job = JobRecord(
                kind="prompt_profile", status="queued",
                entity_type=entity_type, entity_id=entity.id,
                payload={"project_id": project_id,
                         "entity_type": entity_type,
                         "entity_id": entity.id},
            )
            db.add(job)
            jobs.append(job)
    await db.flush()
    return jobs


async def run_prompt_profile(payload: dict, db: AsyncSession) -> dict:
    """Local job handler: generate one entity's profile. No ComfyUI round-trip."""
    entity_type = payload["entity_type"]
    model = ENTITY_MODELS.get(entity_type)
    entity = await db.get(model, payload["entity_id"]) if model else None
    if entity is None:
        return {"skipped": "entity gone"}
    profile = await ensure_prompt_profile(entity, entity_type, db)
    await db.commit()
    return {"generated": profile is not None}


register_local("prompt_profile", run_prompt_profile)

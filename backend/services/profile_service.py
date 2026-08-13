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

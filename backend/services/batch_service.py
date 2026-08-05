"""Batch spec expansion (Phase 1, KAN-26).

A batch spec names a *scope* (project | scene | shot | entity) and a set of
targets; expanding it fans out one job per target per variant. The worker then
runs those jobs unattended (Phase 0), which is what turns "render the whole
project" into an overnight run rather than a fire-hose of inline submits.

Seed policy is a placeholder here (random per variant) — KAN-35 replaces
`_resolve_seed`. `run_after` propagation to child jobs is KAN-29; this task only
records it on the batch.
"""
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Batch, JobRecord, Scene, Shot, Character, Location, Prop, GeneratedImage,
)
from services.comfyui_service import construct_prompt

VALID_SCOPES = {"project", "scene", "shot", "entity"}
SEED_MAX = 1000000000000000


def _resolve_seed(spec: dict, variant_index: int) -> int:
    """Placeholder until KAN-35. Every variant gets its own random seed."""
    return random.randint(1, SEED_MAX)


async def _resolve_targets(scope: str, target_ids: list[str], db: AsyncSession):
    """Return an ordered list of (target_type, target_id) for the scope."""
    target_ids = target_ids or []
    if scope == "project":
        rows = (await db.execute(
            select(Scene).where(Scene.project_id.in_(target_ids)).order_by(Scene.sort_order)
        )).scalars().all()
        return [("scene", s.id) for s in rows]
    if scope == "scene":
        rows = (await db.execute(
            select(Scene).where(Scene.id.in_(target_ids)).order_by(Scene.sort_order)
        )).scalars().all()
        return [("scene", s.id) for s in rows]
    if scope == "shot":
        rows = (await db.execute(
            select(Shot).where(Shot.scene_id.in_(target_ids)).order_by(Shot.sort_order)
        )).scalars().all()
        return [("shot", s.id) for s in rows]
    if scope == "entity":
        targets = []
        for model, etype in ((Character, "character"), (Location, "location"), (Prop, "prop")):
            rows = (await db.execute(select(model).where(model.id.in_(target_ids)))).scalars().all()
            targets += [(etype, r.id) for r in rows]
        return targets
    raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")


async def _materialize_job(target_type, target_id, spec, seed, db) -> JobRecord:
    """Build one JobRecord for a target+variant, creating the owning row when the
    kind needs one (scene_image → a queued GeneratedImage)."""
    kind = spec["kind"]
    priority = int(spec.get("priority") or 0)
    base = {**(spec.get("params") or {}), "seed": seed}
    if spec.get("workflow"):
        base["workflow"] = spec["workflow"]

    if kind == "scene_image" and target_type == "scene":
        prompt = await construct_prompt(target_id, db)
        gen = GeneratedImage(scene_id=target_id, prompt=prompt, status="queued")
        db.add(gen)
        await db.flush()
        return JobRecord(
            kind=kind, status="queued", seed=seed, priority=priority,
            entity_type="generated_image", entity_id=gen.id,
            payload={**base, "prompt": prompt, "generation_id": gen.id},
        )

    # Generic: link the job directly to its target; the handler for `kind`
    # resolves the rest at build time.
    return JobRecord(
        kind=kind, status="queued", seed=seed, priority=priority,
        entity_type=target_type, entity_id=target_id,
        payload={**base, f"{target_type}_id": target_id},
    )


async def create_batch(spec: dict, db: AsyncSession) -> tuple[Batch, list[JobRecord]]:
    """Create a Batch and all its child jobs from a spec, in the caller's
    transaction. Returns (batch, jobs). Raises ValueError for an unknown scope
    (router → 422)."""
    scope = spec.get("scope")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")

    variants = max(1, int(spec.get("variants") or 1))
    # project scope defaults to the batch's own project when no targets given.
    target_ids = spec.get("target_ids") or ([spec["project_id"]] if scope == "project" else [])
    targets = await _resolve_targets(scope, target_ids, db)

    batch = Batch(
        project_id=spec["project_id"],
        name=spec.get("name"),
        kind=spec.get("kind"),
        spec=spec,
        params=spec.get("params"),
        status="pending",
        run_after=_parse_run_after(spec.get("run_after")),
    )
    db.add(batch)
    await db.flush()

    jobs: list[JobRecord] = []
    for target_type, target_id in targets:
        for v in range(variants):
            seed = _resolve_seed(spec, v)
            job = await _materialize_job(target_type, target_id, spec, seed, db)
            job.batch_id = batch.id
            db.add(job)
            jobs.append(job)

    await db.commit()
    return batch, jobs


def _parse_run_after(value):
    """Accept an ISO8601 string (or None) for now; relative forms land in KAN-29."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

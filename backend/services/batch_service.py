"""Batch spec expansion (Phase 1, KAN-26).

A batch spec names a *scope* (project | scene | shot | entity) and a set of
targets; expanding it fans out one job per target per variant. The worker then
runs those jobs unattended (Phase 0), which is what turns "render the whole
project" into an overnight run rather than a fire-hose of inline submits.

Seed policy is a placeholder here (random per variant) — KAN-35 replaces
`_resolve_seed`. `run_after` propagation to child jobs is KAN-29; this task only
records it on the batch.
"""
import os
import re
import random
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Batch, JobRecord, Scene, Shot, Character, Location, Prop, GeneratedImage,
)
from services.comfyui_service import construct_prompt
from services.seed_policy import resolve_seed

VALID_SCOPES = {"project", "scene", "shot", "entity"}
SEED_MAX = 1000000000000000

COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

# Seed averages (bytes) for the batch-create size estimate. These are rough
# starting points — tune from real COMFY_OUTPUT_DIR measurements. A batch is
# usually one kind, so the estimate is job_count × the kind's average.
KIND_AVG_BYTES = {
    "scene_image": 2_000_000,
    "asset_txt2img": 2_000_000,
    "asset_img2img": 2_000_000,
    "controlled_image": 2_500_000,
    "video": 15_000_000,
    "mesh": 8_000_000,
}
DEFAULT_AVG_BYTES = 2_000_000
# Require this multiple of the estimate to be free before accepting a batch.
DISK_SAFETY_MARGIN = float(os.environ.get("BATCH_DISK_MARGIN", "1.5"))


def _avg_bytes(kind: str) -> int:
    return KIND_AVG_BYTES.get(kind, DEFAULT_AVG_BYTES)


def free_output_bytes() -> int:
    """Free bytes on COMFY_OUTPUT_DIR's filesystem. Returns a huge sentinel when
    the dir is absent (e.g. tests / non-Docker) so the guard never false-trips."""
    try:
        return shutil.disk_usage(COMFY_OUTPUT_DIR).free
    except OSError:
        return 1 << 60


async def estimate_output_bytes(spec: dict, db: AsyncSession) -> tuple[int, int]:
    """Return (estimated_bytes, job_count) for a spec without creating anything."""
    scope = spec.get("scope")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")
    variants = max(1, int(spec.get("variants") or 1))
    target_ids = spec.get("target_ids") or ([spec["project_id"]] if scope == "project" else [])
    targets = await _resolve_targets(scope, target_ids, db)
    job_count = len(targets) * variants
    return job_count * _avg_bytes(spec.get("kind")), job_count


async def _resolve_targets(scope: str, target_ids: list[str], db: AsyncSession):
    """Return an ordered list of (target_type, target_id, obj) for the scope."""
    target_ids = target_ids or []
    if scope == "project":
        rows = (await db.execute(
            select(Scene).where(Scene.project_id.in_(target_ids)).order_by(Scene.sort_order)
        )).scalars().all()
        return [("scene", s.id, s) for s in rows]
    if scope == "scene":
        rows = (await db.execute(
            select(Scene).where(Scene.id.in_(target_ids)).order_by(Scene.sort_order)
        )).scalars().all()
        return [("scene", s.id, s) for s in rows]
    if scope == "shot":
        rows = (await db.execute(
            select(Shot).where(Shot.scene_id.in_(target_ids)).order_by(Shot.sort_order)
        )).scalars().all()
        return [("shot", s.id, s) for s in rows]
    if scope == "entity":
        targets = []
        for model, etype in ((Character, "character"), (Location, "location"), (Prop, "prop")):
            rows = (await db.execute(select(model).where(model.id.in_(target_ids)))).scalars().all()
            targets += [(etype, r.id, r) for r in rows]
        return targets
    raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")


async def _materialize_job(target_type, target_id, spec, seed, db) -> JobRecord:
    """Build one JobRecord for a target+variant, creating the owning row when the
    kind needs one (scene_image → a queued GeneratedImage). The resolved seed is
    recorded on the owning row's params so a past run can be reproduced exactly."""
    kind = spec["kind"]
    priority = int(spec.get("priority") or 0)
    base = {**(spec.get("params") or {}), "seed": seed}
    if spec.get("workflow"):
        base["workflow"] = spec["workflow"]

    if kind == "scene_image" and target_type == "scene":
        prompt = await construct_prompt(target_id, db)
        gen = GeneratedImage(scene_id=target_id, prompt=prompt, status="queued",
                             params={"seed": seed, "seed_policy": spec.get("seed_policy") or "random"})
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
    run_after = parse_run_after(spec.get("run_after"))  # raises ValueError -> router 422
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
        run_after=run_after,
    )
    db.add(batch)
    await db.flush()

    policy = spec.get("seed_policy") or "random"
    base_seed = spec.get("base_seed")
    project_id = spec["project_id"]

    jobs: list[JobRecord] = []
    for target_type, target_id, target_obj in targets:
        # `locked` prefers the entity's own locked_seed (scenes/shots have none).
        locked_seed = (getattr(target_obj, "prompt_profile", None) or {}).get("locked_seed")
        for v in range(variants):
            seed = resolve_seed(policy, {
                "project_id": project_id,
                "target_id": target_id,
                "variant_index": v,
                "locked_seed": locked_seed,
                "base_seed": base_seed,
            })
            job = await _materialize_job(target_type, target_id, spec, seed, db)
            job.batch_id = batch.id
            # Overnight start: the worker skips a job until scheduled_after passes.
            job.scheduled_after = run_after
            db.add(job)
            jobs.append(job)

    await db.commit()
    return batch, jobs


_REL_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
_TONIGHT_HOUR = 23  # naive-UTC hour for "tonight"


def parse_run_after(value, now: datetime | None = None) -> datetime | None:
    """Parse a batch start time. Explicit forms only — ambiguity is rejected.

    Accepts: None/"" -> now (immediate); an ISO8601 timestamp; a relative
    offset ``+<N><s|m|h|d>`` (e.g. ``+4h``); or the literal ``tonight`` (the
    next ``23:00`` UTC). Anything else raises ValueError so the router can 422.
    Results are normalized to naive UTC to match the worker's clock.
    """
    now = now or datetime.utcnow()
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _to_naive_utc(value)

    s = str(value).strip()
    low = s.lower()

    if low == "tonight":
        t = now.replace(hour=_TONIGHT_HOUR, minute=0, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)

    m = re.fullmatch(r"\+\s*(\d+)\s*([smhd])", low)
    if m:
        return now + timedelta(**{_REL_UNITS[m.group(2)]: int(m.group(1))})

    try:
        return _to_naive_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError(
            f"Unparseable run_after '{value}'. Use an ISO8601 timestamp, "
            f"a relative offset like '+4h', or 'tonight'."
        )


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── progress / cancel / retry (KAN-27) ─────────────────────────────────────

_JOB_STATES = ("queued", "running", "completed", "failed", "cancelled")
_TERMINAL = ("completed", "failed", "cancelled")


async def batch_counts(batch_id: str, db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(JobRecord.status, func.count())
        .where(JobRecord.batch_id == batch_id)
        .group_by(JobRecord.status)
    )).all()
    counts = {s: 0 for s in _JOB_STATES}
    for status, n in rows:
        counts[status] = counts.get(status, 0) + n
    counts["total"] = sum(counts[s] for s in _JOB_STATES)
    return counts


def derive_status(counts: dict) -> str:
    """Overall batch status from its jobs' aggregate counts."""
    if counts["total"] == 0:
        return "pending"
    active = counts["queued"] + counts["running"]
    if active == 0:  # everything terminal
        if counts["completed"] > 0:
            return "completed"
        if counts["failed"] > 0:
            return "failed"
        return "cancelled"
    if counts["running"] > 0 or counts["completed"] > 0:
        return "running"
    return "pending"


def _not_started(counts: dict) -> bool:
    return (counts["total"] > 0
            and counts["running"] == 0 and counts["completed"] == 0
            and counts["failed"] == 0 and counts["cancelled"] == 0)


async def batch_summary(batch: Batch, db: AsyncSession, include_jobs: bool = False) -> dict:
    counts = await batch_counts(batch.id, db)
    # An explicit cancel is a deliberate terminal state — honour it even if a
    # job happened to complete before cancellation landed.
    if batch.status == "cancelled":
        status = "cancelled"
    elif batch.run_after and batch.run_after > datetime.utcnow() and _not_started(counts):
        # Queued but waiting for its overnight start time.
        status = "scheduled"
    else:
        status = derive_status(counts)
    summary = {
        "id": batch.id,
        "project_id": batch.project_id,
        "name": batch.name,
        "kind": batch.kind,
        "status": status,
        "run_after": batch.run_after.isoformat() if batch.run_after else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
        "counts": counts,
    }
    if include_jobs:
        # Only the single-batch view needs per-job detail (status + error) to
        # back the queue panel's expandable row; the list view stays light.
        rows = (await db.execute(
            select(JobRecord).where(JobRecord.batch_id == batch.id)
            .order_by(JobRecord.created_at.asc())
        )).scalars().all()
        summary["jobs"] = [
            {
                "job_id": j.job_id,
                "kind": j.kind,
                "status": j.status,
                "entity_type": j.entity_type,
                "entity_id": j.entity_id,
                "error": j.error,
            }
            for j in rows
        ]
    return summary


async def cancel_batch(batch: Batch, db: AsyncSession) -> dict:
    """Cancel every non-terminal child job. In-flight ComfyUI work is left to
    finish — we simply stop recording its result. Completed/failed jobs are
    untouched."""
    jobs = (await db.execute(
        select(JobRecord).where(
            JobRecord.batch_id == batch.id,
            JobRecord.status.in_(["queued", "running"]),
        )
    )).scalars().all()
    now = datetime.utcnow()
    for job in jobs:
        job.status = "cancelled"
        job.finished_at = now
        job.error = job.error or "Batch cancelled"
    batch.status = "cancelled"
    await db.commit()
    return await batch_summary(batch, db)


async def retry_failed(batch: Batch, db: AsyncSession) -> dict:
    """Reset failed jobs to queued with a clean slate. Cancelled jobs are NOT
    resurrected — cancellation is a deliberate stop."""
    jobs = (await db.execute(
        select(JobRecord).where(
            JobRecord.batch_id == batch.id,
            JobRecord.status == "failed",
        )
    )).scalars().all()
    for job in jobs:
        job.status = "queued"
        job.attempts = 0
        job.error = None
        job.finished_at = None
        job.scheduled_after = None
    if jobs:
        batch.status = "pending"
    await db.commit()
    return await batch_summary(batch, db)


async def list_project_batches(project_id: str, db: AsyncSession) -> list[dict]:
    batches = (await db.execute(
        select(Batch).where(Batch.project_id == project_id).order_by(Batch.created_at.desc())
    )).scalars().all()
    return [await batch_summary(b, db) for b in batches]

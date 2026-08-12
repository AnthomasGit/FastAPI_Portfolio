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
from typing import Awaitable, Callable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Batch, JobRecord, Scene, Shot, Character, Location, Prop, GeneratedImage,
)
from services.comfyui_service import construct_prompt
from services.seed_policy import resolve_seed
from services.chains import validate_chain

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
    # MEASURED: a real 10s H3 clip at the default 0.3 megapixels came out at
    # 555 KB (h264 736x416 + aac). Padded ~7x because megapixels is user-facing
    # (up to 1.0) and duration up to 15s, both of which scale the output. The
    # earlier 40 MB placeholder over-estimated by ~70x, which would have
    # rejected batches that fit comfortably.
    "shot_clip": 4_000_000,
    # Sheet kinds fan out to ~10 cells per target, so the per-job average is one
    # cell; the job count already reflects the fan-out.
    "character_sheet": 2_000_000,
    "prop_sheet": 2_000_000,
    "location_plate": 2_500_000,
    "plate_angles": 10_000_000,
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


# Some kinds operate on a finer grain than the scope names. A project-scope
# `shot_clip` batch means "every shot in every scene", not "every scene" — the
# scope says WHICH part of the project, the grain says what a job is ABOUT.
TARGET_GRAIN = {"shot_clip": "shot"}


def target_grain(kind: str | None) -> str:
    return TARGET_GRAIN.get(kind or "", "scene")


async def estimate_output_bytes(spec: dict, db: AsyncSession) -> tuple[int, int]:
    """Return (estimated_bytes, job_count) for a spec without creating anything."""
    scope = spec.get("scope")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")
    variants = max(1, int(spec.get("variants") or 1))
    target_ids = spec.get("target_ids") or ([spec["project_id"]] if scope == "project" else [])
    # Grain must match what create_batch will use or the estimate counts scenes
    # while the batch renders shots — off by the whole shot-list multiplier.
    targets = await _resolve_targets(scope, target_ids, db, grain=target_grain(spec.get("kind")))
    job_count = len(targets) * variants
    return job_count * _avg_bytes(spec.get("kind")), job_count


async def _resolve_targets(scope: str, target_ids: list[str], db: AsyncSession,
                           grain: str = "scene"):
    """Return an ordered list of (target_type, target_id, obj) for the scope.

    `grain` refines project/scene scopes down to shots for kinds whose unit of
    work is a shot. NOTE: scope="shot" takes SCENE ids despite its name — it
    means "the shots of these scenes", and predates the grain concept.
    """
    target_ids = target_ids or []
    if scope == "project":
        if grain == "shot":
            # Story order across scenes: an overnight run should render the film
            # front to back, so a partial result is still watchable in sequence.
            rows = (await db.execute(
                select(Shot).join(Scene, Shot.scene_id == Scene.id)
                .where(Scene.project_id.in_(target_ids))
                .order_by(Scene.sort_order, Shot.sort_order)
            )).scalars().all()
            return [("shot", s.id, s) for s in rows]
        rows = (await db.execute(
            select(Scene).where(Scene.project_id.in_(target_ids)).order_by(Scene.sort_order)
        )).scalars().all()
        return [("scene", s.id, s) for s in rows]
    if scope == "scene":
        if grain == "shot":
            rows = (await db.execute(
                select(Shot).join(Scene, Shot.scene_id == Scene.id)
                .where(Shot.scene_id.in_(target_ids))
                .order_by(Scene.sort_order, Shot.sort_order)
            )).scalars().all()
            return [("shot", s.id, s) for s in rows]
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


# kind -> materializer. A materializer builds the JobRecord(s) for ONE
# target+variant and creates whatever owning row the kind needs, in the caller's
# transaction (it must NOT commit — create_batch owns the transaction).
#
# Registry rather than an if/elif chain, and — importantly — rather than a
# generic fallback. The old fallback emitted `payload={f"{target_type}_id": ...}`
# for every unhandled kind, which every handler except scene_image rejects at
# build time: a batch of N such jobs was accepted, queued, and then burned its
# retries on a KeyError at 3am. Failing at request time with a clear message is
# strictly better. Kinds are registered as their materializers land (KAN-51).
Materializer = Callable[..., Awaitable[list[JobRecord]]]
BATCH_KINDS: dict[str, Materializer] = {}
_ENTITY_MODELS = {"character": Character, "location": Location, "prop": Prop}


def register_materializer(kind: str, fn) -> None:
    BATCH_KINDS[kind] = fn


async def _materialize_scene_image(target_type, target_id, spec, seed, base, priority, db, batch):
    prompt = await construct_prompt(target_id, db)
    gen = GeneratedImage(scene_id=target_id, prompt=prompt, status="queued",
                         params={"seed": seed, "seed_policy": spec.get("seed_policy") or "random"})
    db.add(gen)
    await db.flush()
    return [JobRecord(
        kind="scene_image", status="queued", seed=seed, priority=priority, max_attempts=1,
        entity_type="generated_image", entity_id=gen.id,
        payload={**base, "prompt": prompt, "generation_id": gen.id,
                 "scene_id": target_id,
                 "identity_refs": bool(spec.get("identity_refs")),
                 "use_plate": bool(spec.get("use_plate", True))},
    )]


register_materializer("scene_image", _materialize_scene_image)


async def _materialize_shot_clip(target_type, target_id, spec, seed, base, priority, db, batch):
    """One H3 reference-to-video clip for one shot.

    The payload deliberately carries ids and knobs only: references, prompt and
    audio are resolved at BUILD time (see shot_clip_service), because a batch may
    sit queued for hours and staged files or canonical picks can change in the
    meantime. The owning GeneratedVideo is created here so the Queue shows a
    placeholder immediately and a cancel has a row to reflect onto.
    """
    from services.shot_clip_service import create_shot_clip_rows, DEFAULT_SHOT_CLIP_WORKFLOW

    shot = await db.get(Shot, target_id)
    if shot is None:
        raise ValueError(f"Shot {target_id} not found")

    video = await create_shot_clip_rows(shot, spec, seed, db)
    # The shot's own audio pick, unless the spec overrides it for the whole run.
    audio_ids = spec.get("ref_audio_ids")
    if audio_ids is None:
        audio_ids = [shot.reference_audio_id] if shot.reference_audio_id else []

    payload = {k: v for k, v in base.items() if k != "workflow"}
    return [JobRecord(
        kind="shot_clip", status="queued", seed=seed, priority=priority, max_attempts=1,
        entity_type="generated_video", entity_id=video.id,
        payload={
            **payload,
            "shot_id": shot.id,
            "workflow_key": spec.get("workflow") or DEFAULT_SHOT_CLIP_WORKFLOW,
            "generated_video_id": video.id,
            "ref_audio_ids": audio_ids,
            "params": spec.get("params") or {},
        },
    )]


register_materializer("shot_clip", _materialize_shot_clip)


def _entity_sheet_materializer(entity_type: str):
    """Materializer for a character/prop sheet over one entity target.

    Delegates to sheet_service's no-commit core so the cells + contact-sheet
    composite land in THIS batch's transaction — the standalone endpoints create
    their own batch and commit, which would persist a half-built one here.
    """
    async def _materialize(target_type, target_id, spec, seed, base, priority, db, batch):
        from services import sheet_service

        if target_type != entity_type:
            return []          # an entity batch mixes types; skip the others
        entity = await db.get(_ENTITY_MODELS[entity_type], target_id)
        if entity is None:
            raise ValueError(f"{entity_type.title()} {target_id} not found")
        return await sheet_service.build_sheet_jobs(
            entity, entity_type, batch, db,
            cells=spec.get("cells"),
            workflow=spec.get("workflow"),
            from_canonical=bool(spec.get("from_canonical", True)),
        )
    return _materialize


register_materializer("character_sheet", _entity_sheet_materializer("character"))
register_materializer("prop_sheet", _entity_sheet_materializer("prop"))


async def _materialize_location_plate(target_type, target_id, spec, seed, base, priority, db, batch):
    """A location's establishing plate, optionally followed by the 360 angle set.

    The angles job depends on the plate job rather than reading its output
    directly: create_plate_angles needs Location.plate_asset_image_id, which is
    only set by the plate job's on_complete. `$from_parent` can't help — it
    yields an image_url, not an asset id — so the angles builder re-reads the
    location at build time, which the dependency makes safe.
    """
    from services import plate_service

    if target_type != "location":
        return []
    loc = await db.get(Location, target_id)
    if loc is None:
        raise ValueError(f"Location {target_id} not found")

    params = spec.get("params") or {}
    jobs = await plate_service.build_plate_jobs(
        loc, db,
        width=params.get("width"), height=params.get("height"),
        workflow=spec.get("workflow"), batch=batch,
    )
    if spec.get("with_angles"):
        jobs += await plate_service.build_angles_jobs(
            loc, db,
            angles=spec.get("angles"),
            double_ref=bool(spec.get("double_ref", True)),
            steps=params.get("steps"),
            depends_on_job_id=jobs[0].job_id,
            batch=batch,
        )
    return jobs


register_materializer("location_plate", _materialize_location_plate)


async def _materialize_job(target_type, target_id, spec, seed, db, batch=None) -> list[JobRecord]:
    """Build the JobRecord(s) for one target+variant via the kind's materializer.

    Returns a list because some kinds fan out (a sheet is N cells + a composite).
    The resolved seed is recorded on the owning row's params so a past run can be
    reproduced exactly. Raises ValueError for an unregistered kind -> router 422.
    """
    kind = spec["kind"]
    priority = int(spec.get("priority") or 0)
    base = {**(spec.get("params") or {}), "seed": seed}
    if spec.get("workflow"):
        base["workflow"] = spec["workflow"]

    materializer = BATCH_KINDS.get(kind)
    if materializer is None:
        raise ValueError(
            f"Batch kind '{kind}' cannot be expanded into runnable jobs "
            f"(known kinds: {', '.join(sorted(BATCH_KINDS))})."
        )
    return await materializer(target_type, target_id, spec, seed, base, priority, db, batch)


async def _materialize_chain(chain, target_type, target_id, spec, seed, batch, db) -> list[JobRecord]:
    """Expand one chain over one target into a linked list of JobRecords.

    Stage 0 is a normal root job (its owning row created by the standard
    per-kind materializer); each later stage ``depends_on`` the previous and
    takes its output via ``{"$from_parent": "image_url"}``, so the worker runs
    them in order and its cascade-cancel drops only this target's tail if a
    stage fails. Downstream stages currently assume a GeneratedImage owning row
    (the scene-still pipelines); asset-image chains are declared but validate
    out today, so that path is never reached yet."""
    stages = chain.stages
    root_spec = {**spec, "kind": stages[0].kind}
    if stages[0].workflow:
        root_spec["workflow"] = stages[0].workflow
    # A chain's root stage is a single-job kind by construction (every declared
    # chain starts with scene_image / asset_txt2img), so take the one job.
    root_jobs = await _materialize_job(target_type, target_id, root_spec, seed, db, batch)
    root = root_jobs[0]
    root.batch_id = batch.id
    db.add(root)
    await db.flush()  # root.job_id for the next stage's dependency link
    jobs = [root]

    prev = root
    for stage in stages[1:]:
        scene_id = target_id if target_type == "scene" else None
        gen = GeneratedImage(scene_id=scene_id, status="queued", kind=stage.kind,
                             params={"chain": chain.name, "source_job_id": prev.job_id})
        db.add(gen)
        await db.flush()
        payload = {
            (stage.parent_input or "source"): {"$from_parent": "image_url"},
            "generation_id": gen.id,
            f"{target_type}_id": target_id,
        }
        if stage.workflow:
            payload["workflow"] = stage.workflow
        if stage.kind == "color_match":
            payload["reference_image"] = spec.get("color_match_reference")
            payload["film_grain"] = bool(spec.get("film_grain"))
        job = JobRecord(
            kind=stage.kind, status="queued", priority=int(spec.get("priority") or 0),
            batch_id=batch.id, entity_type="generated_image", entity_id=gen.id,
            depends_on_job_id=prev.job_id, payload=payload,
        )
        db.add(job)
        await db.flush()
        jobs.append(job)
        prev = job
    return jobs


async def create_batch(spec: dict, db: AsyncSession) -> tuple[Batch, list[JobRecord]]:
    """Create a Batch and all its child jobs from a spec, in the caller's
    transaction. Returns (batch, jobs). Raises ValueError for an unknown scope
    (router → 422)."""
    scope = spec.get("scope")
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown scope '{scope}' (expected one of {sorted(VALID_SCOPES)})")

    # A chain spec must name a runnable chain — validate before creating anything
    # so an unrunnable one (missing exported workflow) half-builds nothing.
    chain = validate_chain(spec["chain"]) if spec.get("chain") else None

    # Same reason, for the kind: everything below flushes rows, so an
    # unmaterializable kind must be refused BEFORE the Batch row exists or a
    # rejected request still leaves a batch behind.
    if chain is None and spec.get("kind") not in BATCH_KINDS:
        raise ValueError(
            f"Batch kind '{spec.get('kind')}' cannot be expanded into runnable jobs "
            f"(known kinds: {', '.join(sorted(BATCH_KINDS))})."
        )

    variants = max(1, int(spec.get("variants") or 1))
    run_after = parse_run_after(spec.get("run_after"))  # raises ValueError -> router 422
    # project scope defaults to the batch's own project when no targets given.
    target_ids = spec.get("target_ids") or ([spec["project_id"]] if scope == "project" else [])
    targets = await _resolve_targets(scope, target_ids, db,
                                     grain=target_grain(spec.get("kind")))

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
            # Chain batches expand into a linked stage graph per target/variant;
            # the chain owns its stages, so the single-job + auto-color-match
            # path below is skipped.
            if chain is not None:
                chain_jobs = await _materialize_chain(chain, target_type, target_id, spec, seed, batch, db)
                for cj in chain_jobs:
                    cj.scheduled_after = run_after
                jobs.extend(chain_jobs)
                continue
            new_jobs = await _materialize_job(target_type, target_id, spec, seed, db, batch)
            if not new_jobs:
                # An entity-scope batch resolves characters, locations AND props;
                # a materializer returns [] for the types it doesn't handle.
                continue
            for job in new_jobs:
                job.batch_id = batch.id
                # Overnight start: the worker skips a job until scheduled_after passes.
                job.scheduled_after = run_after
                db.add(job)
            jobs.extend(new_jobs)

            # "Colour-match to key frame": every generated still gets a dependent
            # color_match job that runs once the still completes (KAN-37). Only
            # the primary job of a target is eligible.
            cm = await _maybe_color_match_job(new_jobs[0], target_type, target_id, spec, batch, db)
            if cm is not None:
                cm.scheduled_after = run_after
                db.add(cm)
                jobs.append(cm)

    await db.commit()
    return batch, jobs


class BatchValidationError(ValueError):
    """A batch spec the API should reject with 422."""


class InsufficientDiskError(Exception):
    """Estimated output would not fit the safety margin (API 507)."""
    def __init__(self, estimated: int, free: int):
        self.estimated = estimated
        self.free = free
        super().__init__(f"Estimated output {estimated} bytes needs "
                         f"{DISK_SAFETY_MARGIN}x free; only {free} bytes free.")


async def assemble_batch(spec: dict, db: AsyncSession) -> dict:
    """Validate + disk-check + create a batch from a spec, returning the API
    response body. Shared by POST /api/batches and preset-run so both produce an
    identical batch from an identical spec (KAN-48). Raises BatchValidationError
    (422) / InsufficientDiskError (507); create_batch's own ValueErrors (unknown
    scope, unrunnable chain) propagate as 422 too."""
    from services.workflow_registry import validate_params

    kind = spec.get("kind")
    if not spec.get("chain"):
        if kind == "shot_clip":
            # Video workflows live in their OWN registry, keyed by workflow key
            # (e.g. "minimax_h3_r2v"), whereas workflow_registry is keyed by
            # ComfyUI graph name — validating against the wrong namespace would
            # reject every valid spec. Validate here so a bad knob 422s before
            # N jobs exist, as well as at build time where it runs again.
            _validate_video_spec(spec)
        else:
            unknown = validate_params(kind, spec.get("workflow"), spec.get("params") or {})
            if unknown:
                raise BatchValidationError(
                    f"Unknown workflow param(s) for kind '{kind}': "
                    f"{', '.join(sorted(unknown))}."
                )
    try:
        parse_run_after(spec.get("run_after"))
    except ValueError as e:
        raise BatchValidationError(str(e)) from e

    estimated_bytes, _ = await estimate_output_bytes(spec, db)
    if estimated_bytes * DISK_SAFETY_MARGIN > free_output_bytes():
        raise InsufficientDiskError(estimated_bytes, free_output_bytes())

    # Resolve (without staging) what each target would render with, so the
    # caller learns about unusable targets NOW rather than from a 3am failure.
    warnings = await preflight(spec, db)

    batch, jobs = await create_batch(spec, db)
    return {
        "batch_id": batch.id,
        "job_count": len(jobs),
        "estimated_output_bytes": estimated_bytes,
        "warnings": warnings,
    }


def _validate_video_spec(spec: dict) -> None:
    """Validate a shot-clip spec against the VIDEO_WORKFLOWS registry."""
    from services.video_service import VIDEO_WORKFLOWS, _resolve_settings
    from services.shot_clip_service import DEFAULT_SHOT_CLIP_WORKFLOW

    key = spec.get("workflow") or DEFAULT_SHOT_CLIP_WORKFLOW
    cfg = VIDEO_WORKFLOWS.get(key)
    if cfg is None:
        raise BatchValidationError(
            f"Unknown video workflow '{key}' "
            f"(known: {', '.join(sorted(VIDEO_WORKFLOWS))})."
        )
    try:
        _resolve_settings(cfg, spec.get("params") or {})
    except ValueError as e:
        raise BatchValidationError(str(e)) from e


async def preflight(spec: dict, db: AsyncSession) -> list[dict]:
    """Per-target warnings for a spec, without creating or staging anything.

    Only shot clips have a meaningful preflight today: a shot whose scene has no
    asset with a primary image cannot render at all, and finding that out at
    creation time (when the dialog can show it) is worth a cheap extra query.
    """
    if spec.get("kind") != "shot_clip" or spec.get("chain"):
        return []
    from services.job_handlers import (
        resolve_scene_entities, select_shot_entities, has_scene_primary,
    )

    scope = spec.get("scope")
    target_ids = spec.get("target_ids") or ([spec["project_id"]] if scope == "project" else [])
    targets = await _resolve_targets(scope, target_ids, db, grain="shot")

    warnings: list[dict] = []
    entities_by_scene: dict[str, list] = {}
    for _t, _id, shot in targets:
        if shot.scene_id not in entities_by_scene:
            entities_by_scene[shot.scene_id] = await resolve_scene_entities(shot.scene_id, db)
        picked = await select_shot_entities(shot, entities_by_scene[shot.scene_id], db)
        usable = [e for etype, e in picked
                  if await has_scene_primary(shot.scene_id, etype, e.id, db)]
        if not usable:
            warnings.append({
                "shot_id": shot.id,
                "shot_number": shot.shot_number,
                "reason": "no referenced asset has a primary image",
            })
    return warnings


async def _maybe_color_match_job(source_job, target_type, target_id, spec, batch, db):
    """A dependent color_match job for a scene_image still, or None.

    The result is a NEW GeneratedImage row linked to the source (params), never
    an overwrite. The source filename is resolved from the parent at build time
    via the {"$from_parent": "image_url"} convention (KAN-22).
    """
    if not spec.get("color_match"):
        return None
    if source_job.kind != "scene_image" or target_type != "scene":
        return None
    reference_url = spec.get("color_match_reference")
    if not reference_url:
        return None

    await db.flush()  # ensure source_job.job_id exists for the dependency
    source_gen_id = source_job.payload.get("generation_id")
    matched = GeneratedImage(
        scene_id=target_id, status="queued", kind="color_match",
        params={"source_generation_id": source_gen_id, "reference_url": reference_url},
    )
    db.add(matched)
    await db.flush()
    return JobRecord(
        kind="color_match", status="queued", priority=int(spec.get("priority") or 0),
        batch_id=batch.id,
        entity_type="generated_image", entity_id=matched.id,
        depends_on_job_id=source_job.job_id,
        payload={
            "source": {"$from_parent": "image_url"},
            "reference_image": reference_url,
            "generation_id": matched.id,
            "film_grain": bool(spec.get("film_grain")),
        },
    )


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

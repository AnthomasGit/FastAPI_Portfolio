"""The `shot_clip` job kind — one MiniMax H3 reference-to-video clip per shot.

This is the unit of work a "Generate everything" batch fans out over: for every
shot in every scene's master shot list, render a clip whose reference slots are
filled with the scene's assets' primary images.

Why this is a separate kind from `video` rather than a reuse of it: `video`
resolves and stages every file at REQUEST time and ships a fully-built
`overrides` dict in its payload. That is right for Clip Studio, where the user
is waiting and wants an immediate 400. It is wrong for a batch, which may sit
queued for hours — staged files can be pruned, and a canonical image may be
re-picked, between enqueue and render. So `shot_clip` carries ids and knobs only
and resolves at BUILD time.

Slot order is the contract shared with the prompt: reference N fills image{N}
and is described as <Subject N> in the composed document, so both come from the
same ordered entity list (see shot_prompt_service).
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Shot, Scene, GeneratedVideo
from services.job_handlers import (
    register,
    resolve_scene_entities,
    select_shot_entities,
    stage_entity_primary_image,
)
from services.video_service import (
    VIDEO_WORKFLOWS,
    _resolve_settings,
    _resolve_reference_audios,
    compose_video_overrides,
    assemble_video_workflow,
    on_complete_video,
)

logger = logging.getLogger(__name__)

DEFAULT_SHOT_CLIP_WORKFLOW = "minimax_h3_r2v"


async def resolve_shot_reference_files(shot: Shot, db: AsyncSession,
                                       max_refs: int) -> tuple[list[str], list[tuple[str, object]]]:
    """Stage a shot's reference images, returning (filenames, entities).

    Both lists are index-aligned and in slot order, so the caller can hand the
    entities to the prompt composer and the filenames to the injector and trust
    that <Subject N> and image{N} describe the same picture.

    Entities without a usable primary image are skipped (a scene commonly has
    props nobody has generated art for yet). Extras beyond the graph's slot
    count are dropped with a warning that names them, so the omission is visible
    in the job log rather than silent.
    """
    entities = await select_shot_entities(
        shot, await resolve_scene_entities(shot.scene_id, db), db
    )

    files: list[str] = []
    used: list[tuple[str, object]] = []
    dropped: list[str] = []
    for etype, entity in entities:
        if len(files) >= max_refs:
            dropped.append(f"{etype} {getattr(entity, 'name', entity.id)}")
            continue
        filename = await stage_entity_primary_image(entity, etype, db)
        if filename is None:
            continue
        files.append(filename)
        used.append((etype, entity))

    if dropped:
        logger.warning(
            "shot %s has more references than the workflow's %d slots; dropped: %s",
            shot.id, max_refs, ", ".join(dropped),
        )
    return files, used


async def build_shot_clip(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    """Resolve a shot's references, prompt and audio, then assemble the graph."""
    shot = await db.get(Shot, payload["shot_id"])
    if shot is None:
        raise ValueError(f"Shot {payload['shot_id']} no longer exists")

    workflow_key = payload.get("workflow_key") or DEFAULT_SHOT_CLIP_WORKFLOW
    cfg = VIDEO_WORKFLOWS.get(workflow_key)
    if cfg is None:
        raise ValueError(f"Unknown video workflow '{workflow_key}'")
    settings = _resolve_settings(cfg, payload.get("params") or {})

    reference_files, entities = await resolve_shot_reference_files(
        shot, db, int(cfg.get("max_refs") or 0)
    )
    if not reference_files:
        # Fail loudly rather than rendering an unanchored clip: a reference-to-
        # video graph with no references produces something unrelated to the
        # film, which is worse than an actionable error in the queue.
        raise ValueError(
            f"Shot {shot.id} has no usable reference images — give its characters/"
            f"locations/props a primary image, or pin references on the shot."
        )

    audio_ids = [a for a in (payload.get("ref_audio_ids") or []) if a]
    audio_files = await _resolve_reference_audios(
        audio_ids[: int(cfg.get("max_ref_audios") or 0)], db
    )

    prompt = payload.get("prompt_override") or shot.clip_prompt
    if not prompt:
        # Compose on the fly and persist, so an overnight batch never silently
        # renders with an empty prompt just because nobody pre-composed.
        from services import shot_prompt_service
        prompt = await shot_prompt_service.compose_for_shot(shot, db)

    overrides = compose_video_overrides(
        cfg, settings,
        prompt=prompt,
        reference_files=reference_files,
        ref_audio_files=audio_files,
    )
    return assemble_video_workflow(
        cfg, overrides,
        seed=payload["seed"],
        job_id=payload.get("job_id") or str(uuid.uuid4()),
        n_images=len(reference_files),
        n_videos=0,
        n_audios=len(audio_files),
        last_frame_present=False,
    )


async def create_shot_clip_rows(shot: Shot, spec: dict, seed: int,
                                db: AsyncSession) -> GeneratedVideo:
    """The owning row for one shot clip, created at batch-expansion time so the
    Queue shows a placeholder immediately and a cancel has something to mark."""
    scene = await db.get(Scene, shot.scene_id)
    workflow_key = spec.get("workflow") or DEFAULT_SHOT_CLIP_WORKFLOW
    video = GeneratedVideo(
        project_id=scene.project_id if scene else None,
        scene_id=shot.scene_id,
        shot_id=shot.id,
        status="queued",
        params={"workflow": workflow_key, "seed": seed, **(spec.get("params") or {})},
    )
    db.add(video)
    await db.flush()
    return video


# on_complete_video is reused verbatim: it reads generated_video_id/job_id from
# the payload (the worker merges handler meta in first), globs the output dir,
# and raises when nothing landed — none of which is specific to the `video` kind.
register("shot_clip", build_shot_clip, on_complete_video)

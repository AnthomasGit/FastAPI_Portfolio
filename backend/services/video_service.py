"""Clip generation: run one of several ComfyUI video workflows for a shot.

Two shapes of input exist and the registry below is what keeps them apart:

* **image-to-video** (``ltx_i2v``) animates a finished beauty-pass still. Input
  is always a **completed** GeneratedImage, never a raw capture — the stage
  dependency rule from 3d-staging-lld-sdlc.md.
* **multi-subject reference** (``ltx_msr``) needs no still at all. It composes
  up to four subject references plus a background plate into LTX-2.3's IC-LoRA
  conditioning guide, driven by a two-part prompt (global identities + local
  script). Its clip therefore hangs off the *shot*, not off a source image.

Mirrors controlled_gen_service's submit path, and asset3d_service's polling
discipline: a clip is only ``completed`` once its file is actually found on
disk. ComfyUI reports ``status_str: success`` even when it silently rejected
the graph at validation and produced nothing — trusting that alone has
already caused one round of phantom "ready" rows in this codebase.
"""

import glob
import os
import random
import shutil
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import GeneratedImage, GeneratedVideo, JobRecord, Reference, Scene, Shot
from services.comfyui_client import load_workflow, load_node_map, inject, submit, poll

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
# LTX-2.3 22B on a single 24GB card is slow; give it plenty of room. Mesh uses 30.
VIDEO_TIMEOUT_MINUTES = int(os.environ.get("VIDEO_TIMEOUT_MINUTES", "45"))
# VHS_VideoCombine writes mp4/webm depending on its configured format; SaveVideo
# (the MSR graph's output node) writes mp4.
VIDEO_EXTENSIONS = (".mp4", ".webm", ".gif")

# Per-workflow capabilities. Mirrors asset3d_service.MESH_WORKFLOWS, but the
# metadata is also served to the UI (GET /api/video-workflows) so the workflow
# picker renders from backend truth instead of a duplicated frontend list.
#
# est_seconds are measured on the RTX 3090 at the defaults below (5s @ 25fps,
# 544x960 base upscaled x2) — see 3d-staging-lld-sdlc.md §11a.
VIDEO_WORKFLOWS = {
    "ltx_i2v": {
        "workflow": "video_ltx_i2v",
        "label": "LTX-2.3 Image-to-Video",
        "blurb": "Animate a finished still. Simplest path when the shot already has a beauty pass.",
        "needs_still": True,
        "max_refs": 0,
        "background": False,
        "driving_video": False,
        "dual_prompt": False,
        "reference_frame_count": False,
        "reference_frame_count_options": [],
        "est_seconds": 120,
        "recommended": False,
    },
    "ltx_msr": {
        "workflow": "video_ltx23_msr",
        "label": "LTX-2.3 Multi-Subject Reference",
        "blurb": "Compose up to 4 characters/props over a background, with dialogue. No still needed.",
        "needs_still": False,
        "max_refs": 4,
        "background": True,
        "driving_video": False,
        "dual_prompt": True,
        # LiconMSR's own identity/detail guide length — separate from the
        # output clip's duration, see comfyui_client.INJECTION_MAP. It's a
        # fixed COMBO on the node (confirmed against ComfyUI's /object_info,
        # not a free-form int), so the options list is authoritative, not a
        # display convenience — an out-of-list value fails ComfyUI validation.
        "reference_frame_count": True,
        "reference_frame_count_options": [17, 25, 33, 41, 49, 57, 65],
        "est_seconds": 90,
        "recommended": True,
    },
}
DEFAULT_WORKFLOW = "ltx_msr"

# Defaults for the MSR graph's constants, matching the verified-working export.
DEFAULT_VIDEO_SETTINGS = {"width": 544, "height": 960, "fps": 25, "duration": 5}
# The node's own default is 41; 17 is what this app defaults to instead.
DEFAULT_REFERENCE_FRAME_COUNT = 17


def list_workflows() -> list[dict]:
    """The registry as a JSON-serialisable list for the workflow picker."""
    return [{"id": key, **cfg} for key, cfg in VIDEO_WORKFLOWS.items()]


async def get_video(video_id: str, db: AsyncSession) -> GeneratedVideo | None:
    result = await db.execute(select(GeneratedVideo).where(GeneratedVideo.id == video_id))
    return result.scalars().first()


async def has_inflight_video(image_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(GeneratedVideo).where(
            GeneratedVideo.source_image_id == image_id,
            GeneratedVideo.status.in_(["queued", "processing"]),
        )
    )
    return result.scalars().first() is not None


async def has_inflight_shot_video(shot_id: str, db: AsyncSession) -> bool:
    """In-flight guard for workflows that hang a clip off a shot, not a still."""
    result = await db.execute(
        select(GeneratedVideo).where(
            GeneratedVideo.shot_id == shot_id,
            GeneratedVideo.status.in_(["queued", "processing"]),
        )
    )
    return result.scalars().first() is not None


def _find_video_by_prefix(job_id: str) -> str | None:
    """Locate the clip VHS_VideoCombine wrote for this job.

    Glob rather than compose the name: the node appends its own counter and
    picks the container extension from its format setting.
    """
    matches = sorted(
        m for m in glob.glob(os.path.join(COMFY_OUTPUT_DIR, f"{job_id}*"))
        if m.lower().endswith(VIDEO_EXTENSIONS)
    )
    return os.path.relpath(matches[0], COMFY_OUTPUT_DIR) if matches else None


def _stage_source_for_load(image: GeneratedImage) -> str:
    """Return an INPUT-relative filename ComfyUI's LoadImage can read.

    The beauty-pass still is a ComfyUI *output* file; LoadImage only reads
    COMFY_INPUT_DIR. Mirrors asset3d_service._resolve_source_for_load /
    asset_image_service's copy-in pattern.
    """
    staged = f"{image.id}_source.png"
    try:
        shutil.copy2(
            os.path.join(COMFY_OUTPUT_DIR, image.image_url),
            os.path.join(COMFY_INPUT_DIR, staged),
        )
    except OSError as e:
        raise ValueError(
            "Source image file is missing — regenerate the beauty pass "
            "before creating a video"
        ) from e
    return staged


def _stage_reference_for_load(ref: Reference) -> str:
    """Return an INPUT-relative filename for a Reference, staging it if needed.

    Background-removed cutouts (``processed_url``) and plain uploads already
    live flat in COMFY_INPUT_DIR. Asset-image references point into
    COMFY_OUTPUT_DIR under a subfolder — the "/" in the url is the established
    signal for that (see asset_image_service / asset3d_service) — so those get
    copied in flat first.

    Raises rather than returning a dangling name: a LoadImage pointing at a
    missing file makes ComfyUI reject the *entire* graph at validation and
    still report success, which surfaces much later as a phantom "no output
    file" failure. With five image slots that is the dominant failure mode, so
    every slot is proved to exist here, named, before anything is submitted.
    """
    source = ref.processed_url or ref.url
    if not source:
        raise ValueError(f"Reference {ref.id} has no image file")

    if "/" not in source:
        if not os.path.exists(os.path.join(COMFY_INPUT_DIR, source)):
            raise ValueError(
                f"Reference image '{source}' is missing from the input directory"
            )
        return source

    staged = f"{ref.id}_ref{os.path.splitext(source)[1] or '.png'}"
    try:
        shutil.copy2(
            os.path.join(COMFY_OUTPUT_DIR, source),
            os.path.join(COMFY_INPUT_DIR, staged),
        )
    except OSError as e:
        raise ValueError(
            f"Reference image '{source}' could not be staged for ComfyUI"
        ) from e
    return staged


async def _resolve_reference_files(reference_ids: list[str], db: AsyncSession) -> list[str]:
    """Load each Reference by id (order preserved) and stage its file."""
    files = []
    for ref_id in reference_ids:
        result = await db.execute(select(Reference).where(Reference.id == ref_id))
        ref = result.scalars().first()
        if not ref:
            raise ValueError(f"Reference {ref_id} not found")
        files.append(_stage_reference_for_load(ref))
    return files


async def generate_video(
    db: AsyncSession,
    workflow_key: str = DEFAULT_WORKFLOW,
    image: GeneratedImage | None = None,
    shot: Shot | None = None,
    reference_ids: list[str] | None = None,
    background_reference_id: str | None = None,
    motion_prompt: str | None = None,
    global_prompt: str | None = None,
    local_prompts: str | None = None,
    params: dict | None = None,
) -> str:
    """Queue a clip. ``workflow_key`` selects which graph out of VIDEO_WORKFLOWS.

    Raises ValueError for anything the caller could have gotten right (unknown
    workflow, missing still, no references, unstageable image) so the router can
    surface a 400 *before* a row is created. Anything that fails after the row
    exists is recorded on the row as ``failed`` instead, matching the existing
    contract that a queued clip always has a status the UI can poll.
    """
    cfg = VIDEO_WORKFLOWS.get(workflow_key)
    if cfg is None:
        raise ValueError(
            f"Unknown video workflow '{workflow_key}' "
            f"(known: {', '.join(sorted(VIDEO_WORKFLOWS))})"
        )

    params = params or {}
    reference_ids = reference_ids or []
    settings = {**DEFAULT_VIDEO_SETTINGS, **{
        k: params[k] for k in DEFAULT_VIDEO_SETTINGS if params.get(k) is not None
    }}
    if cfg.get("reference_frame_count"):
        settings["reference_frame_count"] = (
            params.get("reference_frame_count") or DEFAULT_REFERENCE_FRAME_COUNT
        )
        options = cfg["reference_frame_count_options"]
        if settings["reference_frame_count"] not in options:
            raise ValueError(
                f"{cfg['label']} reference frame count must be one of "
                f"{options} ({settings['reference_frame_count']} given)"
            )
    seed_val = params.get("seed") or random.randint(1, 1000000000000000)
    workflow_name = cfg["workflow"]

    if cfg["needs_still"] and image is None:
        raise ValueError(f"{cfg['label']} requires a completed still")
    if cfg["max_refs"] and not reference_ids:
        raise ValueError(f"{cfg['label']} requires at least one reference image")
    if len(reference_ids) > cfg["max_refs"]:
        raise ValueError(
            f"{cfg['label']} accepts at most {cfg['max_refs']} references "
            f"({len(reference_ids)} given)"
        )

    # Stage every file BEFORE creating the row: a missing image is a caller
    # error, not a failed generation, and ComfyUI would swallow it silently.
    source_image = _stage_source_for_load(image) if image is not None else None
    reference_files = await _resolve_reference_files(reference_ids, db)
    background_file = None
    if background_reference_id:
        background_file = (await _resolve_reference_files([background_reference_id], db))[0]

    # The still already carries the look; the prompt here describes motion.
    prompt_text = motion_prompt or (image.prompt if image is not None else "") or ""

    video = GeneratedVideo(
        project_id=image.project_id if image is not None else None,
        scene_id=(image.scene_id if image is not None else None)
        or (shot.scene_id if shot is not None else None),
        source_image_id=image.id if image is not None else None,
        shot_id=shot.id if shot is not None else None,
        prompt=local_prompts or prompt_text,
        status="queued",
        params={"workflow": workflow_key, "seed": seed_val, **settings},
    )
    db.add(video)
    await db.flush()
    video_id = video.id

    job_id = str(uuid.uuid4())
    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=workflow_name,
        query=local_prompts or prompt_text,
        seed=seed_val,
        job_type="video",
        entity_type="generated_video",
        entity_id=video_id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(workflow_name)
        if workflow.get("_placeholder"):
            raise RuntimeError(
                f"Video workflow not yet configured — export "
                f"{workflow_name}.json from ComfyUI in API format "
                f"(see the file's _instructions field)"
            )
        node_map = load_node_map(workflow_name)

        overrides = {
            "seed": seed_val,
            "filename_prefix": job_id,
            "width": settings["width"],
            "height": settings["height"],
            "fps": settings["fps"],
            "duration": settings["duration"],
        }
        if cfg["dual_prompt"]:
            # PromptRelayEncode: identities up top, the beat-by-beat script below.
            overrides["global_prompt"] = global_prompt or ""
            overrides["local_prompts"] = local_prompts or prompt_text
        else:
            overrides["prompt"] = prompt_text

        if cfg.get("reference_frame_count"):
            # LiconMSR's frame_count widget is a STRING input in the exported
            # graph ("17", not 17) — cast explicitly rather than rely on the
            # caller's type.
            overrides["reference_frame_count"] = str(settings["reference_frame_count"])

        if source_image:
            overrides["image"] = source_image
        # Reference slots fill positionally; slot 1 doubles as "image" for the
        # MSR graph, whose first LoadImage is subject #1 rather than a still.
        for idx, filename in enumerate(reference_files):
            overrides["image" if idx == 0 else f"image{idx + 1}"] = filename
        if background_file:
            overrides["background_image"] = background_file

        workflow = inject(workflow, node_map, overrides)
        prompt_id = await submit(workflow)

        video.status = "processing"
        video.job_id = job_id
        video.prompt_id = prompt_id
        job.status = "processing"
        job.prompt_id = prompt_id
        await db.commit()

    except Exception as e:
        video.status = "failed"
        video.error = str(e)
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.utcnow()
        await db.commit()

    return video_id


async def poll_video(video_id: str, db: AsyncSession) -> GeneratedVideo | None:
    result = await db.execute(select(GeneratedVideo).where(GeneratedVideo.id == video_id))
    video = result.scalars().first()
    if not video:
        return None

    if video.status in ("completed", "failed", "queued"):
        return video

    if not video.prompt_id:
        return video

    job_result = await db.execute(select(JobRecord).where(JobRecord.job_id == video.job_id))
    job = job_result.scalars().first()

    if job and job.created_at:
        if datetime.utcnow() - job.created_at > timedelta(minutes=VIDEO_TIMEOUT_MINUTES):
            video.status = "failed"
            video.error = "Video generation timed out"
            job.status = "failed"
            job.error = "Timed out"
            job.finished_at = datetime.utcnow()
            await db.commit()
            return video

    poll_result = await poll(video.prompt_id)
    if poll_result["status"] == "error":
        video.status = "failed"
        video.error = "ComfyUI reported an error"
        if job:
            job.status = "failed"
            job.error = "ComfyUI error"
            job.finished_at = datetime.utcnow()
        await db.commit()
    elif poll_result["status"] == "completed":
        found = _find_video_by_prefix(video.job_id)
        if found:
            video.video_url = found
            video.status = "completed"
            if job:
                job.status = "completed"
        else:
            # "completed" with no file means the graph was rejected at
            # validation and every output node was skipped.
            video.status = "failed"
            video.error = (
                "ComfyUI finished but produced no video file "
                "(workflow may have failed validation)"
            )
            if job:
                job.status = "failed"
                job.error = "No output file found"
        if job:
            job.finished_at = datetime.utcnow()
        await db.commit()

    return video


async def get_video_file(video_id: str, db: AsyncSession) -> bytes | None:
    result = await db.execute(select(GeneratedVideo).where(GeneratedVideo.id == video_id))
    video = result.scalars().first()
    if not video or not video.video_url:
        return None
    try:
        with open(os.path.join(COMFY_OUTPUT_DIR, video.video_url), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None

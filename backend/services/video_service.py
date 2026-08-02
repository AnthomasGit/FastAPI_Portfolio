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

from database import (
    DrivingVideo, GeneratedImage, GeneratedVideo, JobRecord, Reference, Scene, Shot,
)
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
# picker + settings panel render from backend truth rather than a duplicated
# frontend list.
#
# Each workflow declares its own `settings` — the tunable knobs it actually
# has, since these differ structurally (MSR has width/height, SCAIL-2 derives
# dimensions from the reference image and instead has a frame count that must
# drive two nodes at once). A setting spec:
#   id        param key the caller/UI uses
#   default   value when unset
#   label/help  UI copy
#   options   fixed COMBO -> validated membership, rendered as a <select>
#   min/max/step  numeric range -> validated, rendered as a slider/number
#   inject    injection keys it feeds (default [id]); >1 = one knob, many nodes
#   str_value cast to str before injecting (for COMBO string widgets)
# inject/str_value are backend-only; list_workflows() strips them before the UI
# sees the specs.
#
# est_seconds are measured on the RTX 3090 — see 3d-staging-lld-sdlc.md §11a.
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
        "est_seconds": 120,
        "recommended": False,
        "settings": [],
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
        "est_seconds": 90,
        "recommended": True,
        "settings": [
            {"id": "width", "default": 544, "min": 256, "max": 1280, "label": "Width",
             "help": "Rounds to a multiple of 32 in latent space; the x2 upscaler doubles the output."},
            {"id": "height", "default": 960, "min": 256, "max": 1280, "label": "Height"},
            {"id": "fps", "default": 25, "min": 8, "max": 30, "label": "FPS"},
            {"id": "duration", "default": 5, "min": 1, "max": 20, "label": "Seconds",
             "help": "Clip length = fps × seconds. Drives generation time more than resolution does."},
            {
                "id": "reference_frame_count",
                "default": 17,
                # A fixed COMBO on LiconMSR (confirmed via ComfyUI /object_info,
                # not a free-form int) — an out-of-list value fails validation.
                "options": [17, 25, 33, 41, 49, 57, 65],
                "str_value": True,
                "label": "Reference frames",
                "help": "Higher improves identity/detail retention, but needs more GPU memory.",
            },
        ],
    },
    "scail2_anim": {
        "workflow": "video_scail2_anim",
        "label": "SCAIL-2 Pose Transfer",
        "blurb": "Drive a character from a reference image with the motion of an uploaded video.",
        "needs_still": False,
        "max_refs": 1,
        "background": False,
        "driving_video": True,
        "dual_prompt": False,
        "est_seconds": 360,
        "recommended": False,
        "settings": [
            {
                # One knob feeds both the sampler's length and how many driving
                # frames get loaded — if they diverged, motion and output desync.
                "id": "frames",
                "default": 81,
                "min": 17,
                "max": 161,
                "inject": ["length", "driving_frames"],
                "label": "Frames",
                "help": "At 16fps, 81 ≈ 5s. Drives generation time more than anything else.",
            },
            {
                "id": "pose_strength",
                "default": 1.0,
                "min": 0,
                "max": 1,
                "step": 0.05,
                "label": "Pose strength",
                "help": "How strictly the character follows the driving motion.",
            },
        ],
    },
}
DEFAULT_WORKFLOW = "ltx_msr"

# Keys of a setting spec that are backend-only and must not reach the client.
_INTERNAL_SETTING_KEYS = ("inject", "str_value")


def _public_settings(specs: list[dict]) -> list[dict]:
    """Strip backend-only keys (inject/str_value) from setting specs."""
    return [
        {k: v for k, v in spec.items() if k not in _INTERNAL_SETTING_KEYS}
        for spec in specs
    ]


def list_workflows() -> list[dict]:
    """The registry as a JSON-serialisable list for the workflow picker."""
    return [
        {**cfg, "id": key, "settings": _public_settings(cfg.get("settings", []))}
        for key, cfg in VIDEO_WORKFLOWS.items()
    ]


def _resolve_settings(cfg: dict, params: dict) -> dict:
    """Validate each declared setting against its spec and return {id: value}.

    Raises ValueError (surfaced as a 400) for a value outside its options or
    numeric range, before any DB row is created.
    """
    resolved = {}
    for spec in cfg.get("settings", []):
        sid = spec["id"]
        val = params.get(sid)
        if val is None:
            val = spec["default"]
        if "options" in spec and val not in spec["options"]:
            raise ValueError(
                f"{cfg['label']} '{spec.get('label', sid)}' must be one of "
                f"{spec['options']} ({val} given)"
            )
        if "min" in spec and val < spec["min"]:
            raise ValueError(
                f"{cfg['label']} '{spec.get('label', sid)}' must be ≥ {spec['min']} ({val} given)"
            )
        if "max" in spec and val > spec["max"]:
            raise ValueError(
                f"{cfg['label']} '{spec.get('label', sid)}' must be ≤ {spec['max']} ({val} given)"
            )
        resolved[sid] = val
    return resolved


def _settings_overrides(cfg: dict, resolved: dict) -> dict:
    """Map resolved setting values onto ComfyUI injection keys.

    A setting feeds the injection key(s) named in its ``inject`` list (default
    just its own id), so one knob (SCAIL-2 ``frames``) can drive several nodes.
    ``str_value`` casts to str for COMBO string widgets (MSR frame_count).
    """
    overrides = {}
    for spec in cfg.get("settings", []):
        val = resolved[spec["id"]]
        if spec.get("str_value"):
            val = str(val)
        for key in spec.get("inject", [spec["id"]]):
            overrides[key] = val
    return overrides


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


async def _resolve_driving_video(driving_video_id: str, db: AsyncSession) -> str:
    """Return the INPUT-relative filename for a DrivingVideo, verifying it exists.

    Uploaded driving videos already live flat in COMFY_INPUT_DIR (that is what
    the upload endpoint writes), so no staging copy is needed — but the file
    must actually be there or VHS_LoadVideo silently fails the whole graph,
    exactly like a dangling LoadImage.
    """
    result = await db.execute(
        select(DrivingVideo).where(DrivingVideo.id == driving_video_id)
    )
    dv = result.scalars().first()
    if not dv:
        raise ValueError(f"Driving video {driving_video_id} not found")
    if not dv.video_url or not os.path.exists(os.path.join(COMFY_INPUT_DIR, dv.video_url)):
        raise ValueError(f"Driving video file '{dv.video_url}' is missing from the input directory")
    return dv.video_url


async def generate_video(
    db: AsyncSession,
    workflow_key: str = DEFAULT_WORKFLOW,
    image: GeneratedImage | None = None,
    shot: Shot | None = None,
    reference_ids: list[str] | None = None,
    background_reference_id: str | None = None,
    driving_video_id: str | None = None,
    motion_prompt: str | None = None,
    global_prompt: str | None = None,
    local_prompts: str | None = None,
    params: dict | None = None,
) -> str:
    """Queue a clip. ``workflow_key`` selects which graph out of VIDEO_WORKFLOWS.

    Raises ValueError for anything the caller could have gotten right (unknown
    workflow, missing still, no references, out-of-range setting, missing
    driving video) so the router can surface a 400 *before* a row is created.
    Anything that fails after the row exists is recorded on the row as
    ``failed`` instead, matching the existing contract that a queued clip
    always has a status the UI can poll.
    """
    cfg = VIDEO_WORKFLOWS.get(workflow_key)
    if cfg is None:
        raise ValueError(
            f"Unknown video workflow '{workflow_key}' "
            f"(known: {', '.join(sorted(VIDEO_WORKFLOWS))})"
        )

    params = params or {}
    reference_ids = reference_ids or []
    settings = _resolve_settings(cfg, params)
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
    if cfg["driving_video"] and not driving_video_id:
        raise ValueError(f"{cfg['label']} requires a driving video")

    # Stage every file BEFORE creating the row: a missing image is a caller
    # error, not a failed generation, and ComfyUI would swallow it silently.
    source_image = _stage_source_for_load(image) if image is not None else None
    reference_files = await _resolve_reference_files(reference_ids, db)
    background_file = None
    if background_reference_id:
        background_file = (await _resolve_reference_files([background_reference_id], db))[0]
    driving_video_file = None
    if driving_video_id:
        driving_video_file = await _resolve_driving_video(driving_video_id, db)

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

        # Per-workflow settings fan out onto their injection keys (one knob may
        # feed several nodes; COMBO widgets get str-cast) — see the registry.
        overrides = {
            "seed": seed_val,
            "filename_prefix": job_id,
            **_settings_overrides(cfg, settings),
        }
        if cfg["dual_prompt"]:
            # PromptRelayEncode: identities up top, the beat-by-beat script below.
            overrides["global_prompt"] = global_prompt or ""
            overrides["local_prompts"] = local_prompts or prompt_text
        else:
            overrides["prompt"] = prompt_text

        if source_image:
            overrides["image"] = source_image
        # Reference slots fill positionally; slot 1 doubles as "image" for the
        # MSR graph, whose first LoadImage is subject #1 rather than a still.
        for idx, filename in enumerate(reference_files):
            overrides["image" if idx == 0 else f"image{idx + 1}"] = filename
        if background_file:
            overrides["background_image"] = background_file
        if driving_video_file:
            overrides["driving_video"] = driving_video_file

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

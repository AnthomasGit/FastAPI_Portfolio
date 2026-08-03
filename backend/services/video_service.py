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
    DrivingVideo, GeneratedImage, GeneratedVideo, JobRecord, Reference,
    ReferenceAudio, Scene, Shot,
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
    "minimax_h3_i2v": {
        "workflow": "video_minimax_h3_i2v",
        "label": "MiniMax H3 Image-to-Video",
        "blurb": "Animate from a first-frame image, optionally interpolating toward a last-frame keyframe.",
        "needs_still": False,
        "max_refs": 0,
        # First frame is the input image: the shot's still by default, or an
        # explicit reference pick. Optional last frame is interpolated toward.
        "first_frame": True,
        "requires_first_frame": True,
        "last_frame": True,
        "background": False,
        "driving_video": False,
        "dual_prompt": False,
        "est_seconds": 150,
        "recommended": False,
        "settings": [
            {
                "id": "sampler_name",
                "default": "res_multistep",
                "options": ["res_multistep", "euler", "dpmpp_2m", "dpmpp_2m_sde", "uni_pc"],
                "label": "Sampler",
                "help": "res_multistep is the recommended sampler for H3.",
            },
            {
                "id": "scheduler",
                "default": "simple",
                "options": ["simple", "beta", "normal", "karras", "sgm_uniform"],
                "label": "Scheduler",
            },
            {"id": "steps", "default": 20, "min": 4, "max": 60, "label": "Steps"},
            {"id": "duration", "default": 10, "min": 2, "max": 15, "label": "Seconds",
             "help": "Trained range is ~5–15s (frames snap to a multiple of 17 at 24fps)."},
            {
                "id": "aspect_ratio",
                "default": "16:9 (Widescreen)",
                "options": [
                    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)",
                    "3:4 (Portrait Standard)", "4:3 (Standard)",
                    "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
                ],
                "label": "Aspect ratio",
            },
            {"id": "megapixels", "default": 0.3, "min": 0.1, "max": 1.0, "step": 0.05,
             "label": "Megapixels",
             "help": "Output size in megapixels. Higher is sharper but slower."},
        ],
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
    "minimax_h3_r2v": {
        "workflow": "video_minimax_h3_r2v",
        "label": "MiniMax H3 Reference-to-Video",
        "blurb": "Compose up to 9 reference images, 3 reference videos (with their soundtracks) and 3 audio clips into a video. No still needed.",
        "needs_still": False,
        "max_refs": 9,
        # R2V-only: reference videos each contribute their embedded soundtrack,
        # plus standalone audio clips. Both consumed by the autogrow node 136.
        "max_ref_videos": 3,
        "max_ref_audios": 3,
        "background": False,
        # R2V references are plain identity/style images, so locations are just
        # more references (there's no dedicated background plate) — let them be
        # picked among the reference slots rather than only as an MSR background.
        "locations_as_refs": True,
        "driving_video": False,
        "dual_prompt": False,
        # Its LoadImage/LoadVideo/LoadAudio slots ship pointing at placeholder
        # files; unused ones must be pruned or the whole graph fails validation.
        "autogrow_slots": True,
        "est_seconds": 150,
        "recommended": False,
        "settings": [
            {
                "id": "sampler_name",
                "default": "res_multistep",
                # A fixed COMBO on KSamplerSelect (validated by ComfyUI). res_multistep
                # is MiniMax H3's recommended sampler; a small curated subset.
                "options": ["res_multistep", "euler", "dpmpp_2m", "dpmpp_2m_sde", "uni_pc"],
                "label": "Sampler",
                "help": "res_multistep is the recommended sampler for H3.",
            },
            {
                "id": "scheduler",
                # beta/normal tend to outperform simple for reference-heavy prompts,
                # so this defaults to beta rather than the graph's shipped 'simple'.
                "default": "beta",
                "options": ["beta", "normal", "simple", "karras", "sgm_uniform"],
                "label": "Scheduler",
                "help": "beta or normal usually beat simple when many references are in play.",
            },
            {"id": "steps", "default": 20, "min": 4, "max": 60, "label": "Steps"},
            {"id": "duration", "default": 10, "min": 2, "max": 15, "label": "Seconds",
             "help": "Trained range is ~5–15s (frames snap to a multiple of 17 at 24fps)."},
            {
                "id": "aspect_ratio",
                "default": "16:9 (Widescreen)",
                "options": [
                    "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)",
                    "3:4 (Portrait Standard)", "4:3 (Standard)",
                    "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)",
                ],
                "label": "Aspect ratio",
            },
            {"id": "megapixels", "default": 0.3, "min": 0.1, "max": 1.0, "step": 0.05,
             "label": "Megapixels",
             "help": "Output size in megapixels. Higher is sharper but slower."},
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


async def _resolve_reference_videos(video_ids: list[str], db: AsyncSession) -> list[str]:
    """Resolve each DrivingVideo id (order preserved) to its input filename.

    R2V reuses the driving-video library as its reference-video source; each
    file must exist or ComfyUI's LoadVideo silently fails the whole graph.
    """
    return [await _resolve_driving_video(vid, db) for vid in video_ids]


async def _resolve_reference_audios(audio_ids: list[str], db: AsyncSession) -> list[str]:
    """Resolve each ReferenceAudio id (order preserved) to its input filename.

    Uploaded audio already lives flat in COMFY_INPUT_DIR, so no staging copy is
    needed — but the file must exist or LoadAudio fails the graph at validation.
    """
    files = []
    for audio_id in audio_ids:
        result = await db.execute(
            select(ReferenceAudio).where(ReferenceAudio.id == audio_id)
        )
        ra = result.scalars().first()
        if not ra:
            raise ValueError(f"Reference audio {audio_id} not found")
        if not ra.audio_url or not os.path.exists(os.path.join(COMFY_INPUT_DIR, ra.audio_url)):
            raise ValueError(f"Reference audio file '{ra.audio_url}' is missing from the input directory")
        files.append(ra.audio_url)
    return files


def _prune_autogrow_slots(
    workflow: dict, node_map: dict, n_images: int, n_videos: int, n_audios: int
) -> dict:
    """Drop unused reference slots from an autogrow graph (MiniMax H3 R2V).

    The exported graph ships with every LoadImage/LoadVideo/LoadAudio slot
    present and pointing at a placeholder filename. A slot left unfilled would
    make ComfyUI reject the *entire* graph at validation (and still report
    success), so any slot beyond the count actually supplied is removed here —
    both its loader node and its reference on the MiniMaxH3ReferenceToVideo node.
    """
    ref_node_id = node_map.get("ref_node")
    ref_inputs = workflow.get(ref_node_id, {}).get("inputs", {}) if ref_node_id else {}

    def drop_node(node_id):
        if node_id:
            workflow.pop(node_id, None)

    for i, node_id in enumerate(node_map.get("image_slots", [])):
        if i >= n_images:
            drop_node(node_id)
            ref_inputs.pop(f"ref_images.ref_image_{i}", None)

    for i, node_id in enumerate(node_map.get("video_slots", [])):
        if i >= n_videos:
            drop_node(node_id)
            ref_inputs.pop(f"ref_videos.ref_video_{i}", None)
            ref_inputs.pop(f"ref_video_audios.ref_video_audio_{i}", None)
    for i, node_id in enumerate(node_map.get("video_component_nodes", [])):
        if i >= n_videos:
            drop_node(node_id)

    for i, node_id in enumerate(node_map.get("audio_slots", [])):
        if i >= n_audios:
            drop_node(node_id)
            ref_inputs.pop(f"ref_audios.ref_audio_{i}", None)

    return workflow


def _prune_optional_last_frame(workflow: dict, node_map: dict) -> dict:
    """Drop the optional last-frame keyframe slot when none was supplied (I2V).

    The graph ships its last_frame LoadImage pointing at a placeholder file;
    left unfilled it would fail the whole graph at validation. Remove both the
    loader node and the last_frame input on the MiniMaxH3ImageToVideo node.
    """
    lf_node = node_map.get("last_frame_node")
    if lf_node:
        workflow.pop(lf_node, None)
    ref_node = node_map.get("ref_node")
    if ref_node:
        workflow.get(ref_node, {}).get("inputs", {}).pop("last_frame", None)
    return workflow


async def generate_video(
    db: AsyncSession,
    workflow_key: str = DEFAULT_WORKFLOW,
    image: GeneratedImage | None = None,
    shot: Shot | None = None,
    reference_ids: list[str] | None = None,
    background_reference_id: str | None = None,
    first_frame_reference_id: str | None = None,
    last_frame_reference_id: str | None = None,
    driving_video_id: str | None = None,
    ref_video_ids: list[str] | None = None,
    ref_audio_ids: list[str] | None = None,
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
    ref_video_ids = ref_video_ids or []
    ref_audio_ids = ref_audio_ids or []
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
    max_ref_videos = cfg.get("max_ref_videos", 0)
    if len(ref_video_ids) > max_ref_videos:
        raise ValueError(
            f"{cfg['label']} accepts at most {max_ref_videos} reference videos "
            f"({len(ref_video_ids)} given)"
        )
    max_ref_audios = cfg.get("max_ref_audios", 0)
    if len(ref_audio_ids) > max_ref_audios:
        raise ValueError(
            f"{cfg['label']} accepts at most {max_ref_audios} reference audio clips "
            f"({len(ref_audio_ids)} given)"
        )
    if cfg["driving_video"] and not driving_video_id:
        raise ValueError(f"{cfg['label']} requires a driving video")
    # First frame is the input image: it can come from the shot's still OR an
    # explicit reference pick, but at least one must be present.
    if cfg.get("requires_first_frame") and image is None and not first_frame_reference_id:
        raise ValueError(f"{cfg['label']} requires a first-frame image")

    # Stage every file BEFORE creating the row: a missing image is a caller
    # error, not a failed generation, and ComfyUI would swallow it silently.
    source_image = _stage_source_for_load(image) if image is not None else None
    reference_files = await _resolve_reference_files(reference_ids, db)
    background_file = None
    if background_reference_id:
        background_file = (await _resolve_reference_files([background_reference_id], db))[0]
    first_frame_file = None
    if first_frame_reference_id:
        first_frame_file = (await _resolve_reference_files([first_frame_reference_id], db))[0]
    last_frame_file = None
    if last_frame_reference_id:
        last_frame_file = (await _resolve_reference_files([last_frame_reference_id], db))[0]
    driving_video_file = None
    if driving_video_id:
        driving_video_file = await _resolve_driving_video(driving_video_id, db)
    ref_video_files = await _resolve_reference_videos(ref_video_ids, db)
    ref_audio_files = await _resolve_reference_audios(ref_audio_ids, db)

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

        # Autogrow graphs (R2V) ship every reference slot present; drop the ones
        # we won't fill before injecting, or ComfyUI rejects the whole graph.
        if cfg.get("autogrow_slots"):
            workflow = _prune_autogrow_slots(
                workflow, node_map,
                len(reference_files), len(ref_video_files), len(ref_audio_files),
            )
        # I2V's optional last-frame slot must be removed when unused, or its
        # placeholder LoadImage fails the graph at validation.
        if cfg.get("last_frame") and not last_frame_file:
            workflow = _prune_optional_last_frame(workflow, node_map)

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
        # An explicit first-frame reference overrides the still as the input image.
        if first_frame_file:
            overrides["image"] = first_frame_file
        # Reference slots fill positionally; slot 1 doubles as "image" for the
        # MSR graph, whose first LoadImage is subject #1 rather than a still.
        for idx, filename in enumerate(reference_files):
            overrides["image" if idx == 0 else f"image{idx + 1}"] = filename
        if background_file:
            overrides["background_image"] = background_file
        if last_frame_file:
            overrides["last_frame"] = last_frame_file
        if driving_video_file:
            overrides["driving_video"] = driving_video_file
        # R2V reference videos + standalone audio fill positionally, same as the
        # image slots above (ref_video / ref_video2 / …, ref_audio / ref_audio2 / …).
        for idx, filename in enumerate(ref_video_files):
            overrides["ref_video" if idx == 0 else f"ref_video{idx + 1}"] = filename
        for idx, filename in enumerate(ref_audio_files):
            overrides["ref_audio" if idx == 0 else f"ref_audio{idx + 1}"] = filename

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

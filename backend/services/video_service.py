"""Image-to-video: turn a finished beauty-pass still into a clip (LTX-2.3).

Input is always a **completed** GeneratedImage, never a raw capture — the
stage dependency rule from 3d-staging-lld-sdlc.md. That keeps video fully
decoupled: anything that can produce a good still can feed it.

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

from database import GeneratedImage, GeneratedVideo, JobRecord, Scene
from services.comfyui_client import load_workflow, load_node_map, inject, submit, poll

WORKFLOW_NAME = os.environ.get("VIDEO_WORKFLOW", "video_ltx_i2v")
COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
# LTX-2.3 22B on a single 24GB card is slow; give it plenty of room. Mesh uses 30.
VIDEO_TIMEOUT_MINUTES = int(os.environ.get("VIDEO_TIMEOUT_MINUTES", "45"))
# VHS_VideoCombine writes mp4/webm depending on its configured format.
VIDEO_EXTENSIONS = (".mp4", ".webm", ".gif")


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


async def generate_video(
    image: GeneratedImage,
    db: AsyncSession,
    motion_prompt: str | None = None,
    params: dict | None = None,
) -> str:
    params = params or {}
    seed_val = params.get("seed") or random.randint(1, 1000000000000000)

    # The still already carries the look; the prompt here describes motion.
    prompt_text = motion_prompt or image.prompt or ""

    video = GeneratedVideo(
        project_id=image.project_id,
        scene_id=image.scene_id,
        source_image_id=image.id,
        prompt=prompt_text,
        status="queued",
        params={"seed": seed_val, "workflow": WORKFLOW_NAME},
    )
    db.add(video)
    await db.flush()
    video_id = video.id

    job_id = str(uuid.uuid4())
    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=WORKFLOW_NAME,
        query=prompt_text,
        seed=seed_val,
        job_type="video",
        entity_type="generated_video",
        entity_id=video_id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(WORKFLOW_NAME)
        if workflow.get("_placeholder"):
            raise RuntimeError(
                f"Video workflow not yet configured — export "
                f"{WORKFLOW_NAME}.json from ComfyUI in API format "
                f"(see the file's _instructions field)"
            )

        node_map = load_node_map(WORKFLOW_NAME)
        source_image = _stage_source_for_load(image)

        workflow = inject(workflow, node_map, {
            "prompt": prompt_text,
            "seed": seed_val,
            "filename_prefix": job_id,
            "image": source_image,
        })

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

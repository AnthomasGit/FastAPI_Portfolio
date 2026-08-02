from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, GeneratedImage, Shot
from schemas.schemas import (
    VideoGenerateRequest,
    GeneratedVideoResponse,
    VideoWorkflowResponse,
)
from services.video_service import (
    DEFAULT_WORKFLOW,
    generate_video,
    get_video,
    get_video_file,
    has_inflight_shot_video,
    has_inflight_video,
    list_workflows,
    poll_video,
)

router = APIRouter()


@router.get("/api/video-workflows", response_model=list[VideoWorkflowResponse])
async def get_video_workflows():
    """The clip-workflow registry, so the picker renders from backend truth."""
    return list_workflows()


@router.post("/api/generate/video", status_code=202)
async def trigger_video_generation(
    data: VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    image = None
    if data.image_id:
        result = await db.execute(
            select(GeneratedImage).where(GeneratedImage.id == data.image_id)
        )
        image = result.scalars().first()
        if not image:
            raise HTTPException(status_code=404, detail="Source image not found")

        # Stage dependency: video consumes a finished still, never an in-flight one.
        if image.status != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Source image is '{image.status}', must be 'completed'",
            )

    shot = None
    if data.shot_id:
        result = await db.execute(select(Shot).where(Shot.id == data.shot_id))
        shot = result.scalars().first()
        if not shot:
            raise HTTPException(status_code=404, detail="Shot not found")

    # Guard whichever thing the clip will hang off, so one shot can't queue two
    # generations at once even when the workflow consumes no still.
    if shot is not None and await has_inflight_shot_video(shot.id, db):
        raise HTTPException(
            status_code=409,
            detail="A clip is already being generated for this shot",
        )
    if image is not None and await has_inflight_video(image.id, db):
        raise HTTPException(
            status_code=409,
            detail="A video is already being generated from this image",
        )

    try:
        video_id = await generate_video(
            db,
            workflow_key=data.workflow or DEFAULT_WORKFLOW,
            image=image,
            shot=shot,
            reference_ids=data.reference_ids,
            background_reference_id=data.background_reference_id,
            motion_prompt=data.motion_prompt,
            global_prompt=data.global_prompt,
            local_prompts=data.local_prompts,
            params=data.params,
        )
    except ValueError as e:
        # Caller-fixable: unknown workflow, missing still, no/too many refs, or
        # a reference whose file can't be staged for ComfyUI.
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"video_id": video_id}


@router.get("/api/generate/video/status/{video_id}", response_model=GeneratedVideoResponse)
async def get_video_status(video_id: str, db: AsyncSession = Depends(get_db)):
    video = await poll_video(video_id, db)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.get("/api/generate/video/file/{video_id}")
async def get_video_binary(video_id: str, db: AsyncSession = Depends(get_db)):
    video = await get_video(video_id, db)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    content = await get_video_file(video_id, db)
    if content is None:
        raise HTTPException(status_code=404, detail="Video file not found")

    media_type = "video/webm" if (video.video_url or "").endswith(".webm") else "video/mp4"
    return Response(content=content, media_type=media_type)

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, GeneratedImage
from schemas.schemas import VideoGenerateRequest, GeneratedVideoResponse
from services.video_service import (
    generate_video,
    get_video,
    get_video_file,
    has_inflight_video,
    poll_video,
)

router = APIRouter()


@router.post("/api/generate/video", status_code=202)
async def trigger_video_generation(
    data: VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
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

    if await has_inflight_video(image.id, db):
        raise HTTPException(
            status_code=409,
            detail="A video is already being generated from this image",
        )

    video_id = await generate_video(
        image, db, motion_prompt=data.motion_prompt, params=data.params
    )
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

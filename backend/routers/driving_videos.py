"""Reusable driving-video library for pose-transfer clip workflows (SCAIL-2).

Uploads land flat in COMFY_INPUT_DIR — the same convention as
references.upload_file — so ComfyUI's VHS_LoadVideo can read them directly and
the existing /api/uploads/file static mount serves previews. Videos can't be
PIL-verified, so the content-type + extension allowlist IS the validation.
"""
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, DrivingVideo
from schemas.schemas import DrivingVideoResponse

router = APIRouter()

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
ALLOWED_EXTS = {".mp4", ".webm", ".mov", ".m4v"}


@router.post("/api/driving-videos", response_model=DrivingVideoResponse, status_code=201)
async def upload_driving_video(
    file: UploadFile = File(...),
    project_id: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=422, detail="File must be a video")

    ext = (Path(file.filename).suffix if file.filename else "").lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported video type '{ext or '?'}' (allowed: {', '.join(sorted(ALLOWED_EXTS))})",
        )

    filename = f"{uuid.uuid4()}{ext}"
    contents = await file.read()
    with open(os.path.join(COMFY_INPUT_DIR, filename), "wb") as f:
        f.write(contents)

    dv = DrivingVideo(
        origin_project_id=project_id,
        label=label or file.filename,
        video_url=filename,
        content_type=file.content_type,
        size_bytes=len(contents),
    )
    db.add(dv)
    await db.commit()
    await db.refresh(dv)
    return dv


@router.get("/api/driving-videos", response_model=List[DrivingVideoResponse])
async def list_driving_videos(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # The library is cross-project by design; project_id is an optional filter,
    # not a hard scope, so a clip uploaded elsewhere stays reachable.
    stmt = select(DrivingVideo).order_by(DrivingVideo.created_at.desc())
    if project_id:
        stmt = stmt.where(DrivingVideo.origin_project_id == project_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/api/driving-videos/{driving_video_id}", status_code=204)
async def delete_driving_video(driving_video_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DrivingVideo).where(DrivingVideo.id == driving_video_id)
    )
    dv = result.scalars().first()
    if not dv:
        raise HTTPException(status_code=404, detail="Driving video not found")

    if dv.video_url:
        try:
            os.remove(os.path.join(COMFY_INPUT_DIR, dv.video_url))
        except OSError:
            pass  # file already gone — the row is what matters
    await db.delete(dv)
    await db.commit()

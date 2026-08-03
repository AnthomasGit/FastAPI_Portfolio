"""Reusable audio-clip library for reference-to-video (MiniMax H3 R2V).

Directly parallels driving_videos: uploads land flat in COMFY_INPUT_DIR (same
convention as references.upload_file) so ComfyUI's LoadAudio can read them
directly and the /api/uploads/file static mount serves previews. Audio can't be
PIL-verified, so the content-type + extension allowlist IS the validation.
"""
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, ReferenceAudio
from schemas.schemas import ReferenceAudioResponse

router = APIRouter()

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
ALLOWED_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}


@router.post("/api/reference-audios", response_model=ReferenceAudioResponse, status_code=201)
async def upload_reference_audio(
    file: UploadFile = File(...),
    project_id: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=422, detail="File must be an audio clip")

    ext = (Path(file.filename).suffix if file.filename else "").lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported audio type '{ext or '?'}' (allowed: {', '.join(sorted(ALLOWED_EXTS))})",
        )

    filename = f"{uuid.uuid4()}{ext}"
    contents = await file.read()
    with open(os.path.join(COMFY_INPUT_DIR, filename), "wb") as f:
        f.write(contents)

    ra = ReferenceAudio(
        origin_project_id=project_id,
        label=label or file.filename,
        audio_url=filename,
        content_type=file.content_type,
        size_bytes=len(contents),
    )
    db.add(ra)
    await db.commit()
    await db.refresh(ra)
    return ra


@router.get("/api/reference-audios", response_model=List[ReferenceAudioResponse])
async def list_reference_audios(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Cross-project by design; project_id is an optional filter, not a hard scope.
    stmt = select(ReferenceAudio).order_by(ReferenceAudio.created_at.desc())
    if project_id:
        stmt = stmt.where(ReferenceAudio.origin_project_id == project_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/api/reference-audios/{reference_audio_id}", status_code=204)
async def delete_reference_audio(reference_audio_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ReferenceAudio).where(ReferenceAudio.id == reference_audio_id)
    )
    ra = result.scalars().first()
    if not ra:
        raise HTTPException(status_code=404, detail="Reference audio not found")

    if ra.audio_url:
        try:
            os.remove(os.path.join(COMFY_INPUT_DIR, ra.audio_url))
        except OSError:
            pass  # file already gone — the row is what matters
    await db.delete(ra)
    await db.commit()

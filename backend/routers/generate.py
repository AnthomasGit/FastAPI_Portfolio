import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db, GeneratedImage, Scene, Project
from schemas.schemas import ControlledGenerateRequest
from services.comfyui_service import generate_scene_image, poll_generation_status
from services.controlled_gen_service import (
    get_capture,
    has_inflight_generation,
    generate_controlled_image,
)

COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://comfyui:8188")

router = APIRouter()


@router.post("/api/generate/scene/{scene_id}")
async def trigger_scene_generation(scene_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Scene not found")

    gen_id = await generate_scene_image(scene_id, db)
    return {"generation_id": gen_id}


@router.post("/api/generate/project/{project_id}")
async def trigger_project_generation(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    scenes = await db.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.sort_order)
    )
    scenes = scenes.scalars().all()

    generation_ids = []
    for scene in scenes:
        gen_id = await generate_scene_image(scene.id, db)
        generation_ids.append(gen_id)

    return {"generation_ids": generation_ids}


@router.post("/api/generate/controlled", status_code=202)
async def trigger_controlled_generation(
    data: ControlledGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    capture = await get_capture(data.capture_id, db)
    if not capture:
        raise HTTPException(status_code=404, detail="Capture not found")

    if await has_inflight_generation(capture.id, db):
        raise HTTPException(
            status_code=409,
            detail="A controlled generation is already in progress for this capture",
        )

    try:
        gen_id = await generate_controlled_image(
            capture, db,
            prompt_override=data.prompt_override,
            params=data.params,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"generation_id": gen_id}


@router.get("/api/generate/status/{generation_id}")
async def get_generation_status(generation_id: str, db: AsyncSession = Depends(get_db)):
    result = await poll_generation_status(generation_id, db)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Generation not found")
    return result


@router.get("/api/generate/image/{generation_id}")
async def get_generated_image(generation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == generation_id))
    gen = result.scalars().first()
    if not gen or not gen.image_url:
        raise HTTPException(status_code=404, detail="Image not found")

    async with httpx.AsyncClient(timeout=10.0) as client:
        img_res = await client.get(
            f"{COMFY_API_URL}/view",
            params={"filename": gen.image_url}
        )
        if img_res.status_code != 200:
            raise HTTPException(status_code=404, detail="Image not found on server")
        return Response(content=img_res.content, media_type="image/png")

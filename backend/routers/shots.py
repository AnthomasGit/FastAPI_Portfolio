from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db, Scene
from schemas.schemas import (
    ShotResponse, ShotCreate, ShotUpdate, ShotReorderRequest,
)
from services import shot_service

router = APIRouter()


async def _get_scene(scene_id: str, db: AsyncSession) -> Scene:
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalars().first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.get("/api/scenes/{scene_id}/shots", response_model=List[ShotResponse])
async def list_shots(scene_id: str, db: AsyncSession = Depends(get_db)):
    await _get_scene(scene_id, db)
    return await shot_service.list_shots(db, scene_id)


@router.post("/api/scenes/{scene_id}/shots", status_code=201, response_model=ShotResponse)
async def create_shot(scene_id: str, data: ShotCreate, db: AsyncSession = Depends(get_db)):
    await _get_scene(scene_id, db)
    return await shot_service.create_shot(db, scene_id, data)


@router.post("/api/scenes/{scene_id}/shots/generate", response_model=List[ShotResponse])
async def generate_shot_list(scene_id: str, db: AsyncSession = Depends(get_db)):
    scene = await _get_scene(scene_id, db)
    try:
        return await shot_service.generate_shot_list(db, scene)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Shot list generation failed: {e}")


@router.put("/api/scenes/{scene_id}/shots/reorder", response_model=List[ShotResponse])
async def reorder_shots(scene_id: str, data: ShotReorderRequest, db: AsyncSession = Depends(get_db)):
    await _get_scene(scene_id, db)
    return await shot_service.reorder_shots(db, scene_id, data.shot_ids)


@router.put("/api/shots/{shot_id}", response_model=ShotResponse)
async def update_shot(shot_id: str, data: ShotUpdate, db: AsyncSession = Depends(get_db)):
    updated = await shot_service.update_shot(db, shot_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Shot not found")
    return updated


@router.delete("/api/shots/{shot_id}", status_code=204)
async def delete_shot(shot_id: str, db: AsyncSession = Depends(get_db)):
    if not await shot_service.delete_shot(db, shot_id):
        raise HTTPException(status_code=404, detail="Shot not found")

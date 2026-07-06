from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Scene, Project
from schemas.schemas import SceneCreate, SceneUpdate, SceneResponse, SceneReorderRequest
from services.reference_service import delete_entity_references

router = APIRouter()

SCENE_LOAD_OPTS = [
    selectinload(Scene.characters),
    selectinload(Scene.locations),
    selectinload(Scene.props),
    selectinload(Scene.references),
    selectinload(Scene.generated_images),
]


@router.get("/api/projects/{project_id}/scenes", response_model=List[SceneResponse])
async def list_scenes(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scene)
        .options(*SCENE_LOAD_OPTS)
        .where(Scene.project_id == project_id)
        .order_by(Scene.sort_order)
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/scenes", status_code=201, response_model=SceneResponse)
async def create_scene(project_id: str, data: SceneCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    scene = Scene(
        project_id=project_id,
        scene_number=data.scene_number,
        slugline=data.slugline,
        screenplay=data.screenplay,
        notes=data.notes,
        sort_order=data.sort_order or data.scene_number,
    )
    db.add(scene)
    await db.commit()

    result = await db.execute(
        select(Scene).options(*SCENE_LOAD_OPTS).where(Scene.id == scene.id)
    )
    return result.scalars().first()


@router.put("/api/scenes/reorder")
async def reorder_scenes(data: SceneReorderRequest, db: AsyncSession = Depends(get_db)):
    for index, scene_id in enumerate(data.scene_ids):
        await db.execute(
            update(Scene).where(Scene.id == scene_id).values(sort_order=index)
        )
    await db.commit()
    return {"status": "ok"}


@router.put("/api/scenes/{scene_id}", response_model=SceneResponse)
async def update_scene(scene_id: str, data: SceneUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scene).options(*SCENE_LOAD_OPTS).where(Scene.id == scene_id)
    )
    scene = result.scalars().first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    if data.slugline is not None:
        scene.slugline = data.slugline
    if data.screenplay is not None:
        scene.screenplay = data.screenplay
    if data.notes is not None:
        scene.notes = data.notes

    await db.commit()

    result = await db.execute(
        select(Scene).options(*SCENE_LOAD_OPTS).where(Scene.id == scene.id)
    )
    return result.scalars().first()


@router.delete("/api/scenes/{scene_id}", status_code=204)
async def delete_scene(scene_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalars().first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    await delete_entity_references(db, "scene", scene_id)
    await db.delete(scene)
    await db.commit()

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import List, Optional

from database import get_db, Scene, Project
from schemas.schemas import (
    SceneCreate, SceneUpdate, SceneResponse, SceneReorderRequest, SceneEntityLinkUpdate,
)
from services.reference_service import delete_entity_references
from services.scene_link_service import (
    VALID_ENTITY_TYPES,
    LinkNotFound,
    LinkInvalid,
    load_scene_links,
    build_scene_response,
    link_entity,
    set_entity_reference,
    unlink_entity,
)

router = APIRouter()

SCENE_LOAD_OPTS = [
    selectinload(Scene.characters),
    selectinload(Scene.locations),
    selectinload(Scene.props),
    selectinload(Scene.references),
    selectinload(Scene.generated_images),
]


async def _scene_response(scene_id: str, db: AsyncSession) -> SceneResponse:
    """Load one scene with its relationships + per-scene links as a SceneResponse."""
    result = await db.execute(
        select(Scene).options(*SCENE_LOAD_OPTS).where(Scene.id == scene_id)
    )
    scene = result.scalars().first()
    links = await load_scene_links(db, [scene_id])
    return build_scene_response(scene, links[scene_id])


@router.get("/api/projects/{project_id}/scenes", response_model=List[SceneResponse])
async def list_scenes(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scene)
        .options(*SCENE_LOAD_OPTS)
        .where(Scene.project_id == project_id)
        .order_by(Scene.sort_order)
    )
    scenes = result.scalars().all()
    links = await load_scene_links(db, [s.id for s in scenes])
    return [build_scene_response(s, links[s.id]) for s in scenes]


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

    return await _scene_response(scene.id, db)


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

    return await _scene_response(scene.id, db)


@router.delete("/api/scenes/{scene_id}", status_code=204)
async def delete_scene(scene_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalars().first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    await delete_entity_references(db, "scene", scene_id)
    await db.delete(scene)
    await db.commit()


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity type: {entity_type}")


@router.post("/api/scenes/{scene_id}/links/{entity_type}/{entity_id}", response_model=SceneResponse)
async def link_scene_entity(
    scene_id: str,
    entity_type: str,
    entity_id: str,
    data: Optional[SceneEntityLinkUpdate] = None,
    db: AsyncSession = Depends(get_db),
):
    _validate_entity_type(entity_type)
    try:
        await link_entity(db, scene_id, entity_type, entity_id, data.reference_id if data else None)
    except LinkNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LinkInvalid as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await _scene_response(scene_id, db)


@router.put("/api/scenes/{scene_id}/links/{entity_type}/{entity_id}", response_model=SceneResponse)
async def set_scene_entity_reference(
    scene_id: str,
    entity_type: str,
    entity_id: str,
    data: SceneEntityLinkUpdate,
    db: AsyncSession = Depends(get_db),
):
    _validate_entity_type(entity_type)
    try:
        await set_entity_reference(db, scene_id, entity_type, entity_id, data.reference_id)
    except LinkNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LinkInvalid as e:
        raise HTTPException(status_code=422, detail=str(e))
    return await _scene_response(scene_id, db)


@router.delete("/api/scenes/{scene_id}/links/{entity_type}/{entity_id}", status_code=204)
async def unlink_scene_entity(
    scene_id: str,
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
):
    _validate_entity_type(entity_type)
    removed = await unlink_entity(db, scene_id, entity_type, entity_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found")

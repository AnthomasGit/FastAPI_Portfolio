"""Prompt/style profile generation + editing (Phase 2, KAN-33).

One generic router covers the three entity types (characters/locations/props)
via the plural path segment, plus the project-level style profile. POST
generates via the LLM; PUT persists a user edit verbatim — the user's edit
always wins over regeneration.
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Character, Location, Prop, Project, AssetImage
from services import ai_service

router = APIRouter()

ENTITY_MODELS = {"characters": Character, "locations": Location, "props": Prop}
SINGULAR = {"characters": "character", "locations": "location", "props": "prop"}


async def _get_entity(entity_type: str, entity_id: str, db: AsyncSession):
    model = ENTITY_MODELS.get(entity_type)
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=f"Invalid entity type '{entity_type}'. Must be one of: {', '.join(ENTITY_MODELS)}",
        )
    entity = (await db.execute(select(model).where(model.id == entity_id))).scalars().first()
    if not entity:
        raise HTTPException(status_code=404, detail=f"{SINGULAR[entity_type]} not found")
    return entity


@router.post("/api/{entity_type}/{entity_id}/prompt-profile")
async def generate_prompt_profile(entity_type: str, entity_id: str,
                                  db: AsyncSession = Depends(get_db)):
    entity = await _get_entity(entity_type, entity_id, db)
    project = await db.get(Project, entity.project_id)
    profile = await ai_service.generate_prompt_profile(
        entity_type=SINGULAR[entity_type],
        name=entity.name,
        description=entity.description,
        style_profile=project.style_profile if project else None,
    )
    entity.prompt_profile = profile
    await db.commit()
    return {"prompt_profile": profile}


@router.put("/api/{entity_type}/{entity_id}/prompt-profile")
async def save_prompt_profile(entity_type: str, entity_id: str,
                              profile: dict = Body(...),
                              db: AsyncSession = Depends(get_db)):
    entity = await _get_entity(entity_type, entity_id, db)
    # Persist the user's edit verbatim — it wins over any regeneration.
    entity.prompt_profile = profile
    await db.commit()
    return {"prompt_profile": profile}


@router.post("/api/projects/{project_id}/style-profile")
async def generate_style_profile(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    style = await ai_service.generate_style_profile(project.idea, project.story_summary)
    project.style_profile = style
    await db.commit()
    return {"style_profile": style}


@router.put("/api/projects/{project_id}/style-profile")
async def save_style_profile(project_id: str, profile: dict = Body(...),
                             db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.style_profile = profile
    await db.commit()
    return {"style_profile": profile}

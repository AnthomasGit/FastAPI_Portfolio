from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Character, Project, Reference
from schemas.schemas import CharacterCreate, CharacterUpdate, CharacterResponse
from services.reference_service import delete_entity_references

router = APIRouter()

CHAR_LOAD_OPTS = [selectinload(Character.references)]


@router.get("/api/projects/{project_id}/characters", response_model=List[CharacterResponse])
async def list_characters(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Character)
        .options(*CHAR_LOAD_OPTS)
        .where(Character.project_id == project_id)
        .order_by(Character.name)
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/characters", status_code=201, response_model=CharacterResponse)
async def create_character(project_id: str, data: CharacterCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    char = Character(
        project_id=project_id,
        name=data.name,
        description=data.description,
        traits=data.traits,
    )
    db.add(char)
    await db.flush()

    # Shim: if reference_url provided, upsert as role='primary' Reference
    if data.reference_url:
        ref = Reference(
            entity_type="character",
            entity_id=char.id,
            role="primary",
            url=data.reference_url,
        )
        db.add(ref)

    await db.commit()

    result = await db.execute(
        select(Character).options(*CHAR_LOAD_OPTS).where(Character.id == char.id)
    )
    return result.scalars().first()


@router.put("/api/characters/{character_id}", response_model=CharacterResponse)
async def update_character(character_id: str, data: CharacterUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Character).where(Character.id == character_id))
    char = result.scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")

    if data.name is not None:
        char.name = data.name
    if data.description is not None:
        char.description = data.description
    if data.traits is not None:
        char.traits = data.traits

    # Shim: if reference_url provided, upsert as role='primary' Reference
    if data.reference_url is not None:
        existing = await db.execute(
            select(Reference).where(
                Reference.entity_type == "character",
                Reference.entity_id == character_id,
                Reference.role == "primary",
            )
        )
        ref = existing.scalars().first()
        if ref:
            ref.url = data.reference_url
        else:
            ref = Reference(
                entity_type="character",
                entity_id=character_id,
                role="primary",
                url=data.reference_url,
            )
            db.add(ref)

    await db.commit()

    result = await db.execute(
        select(Character).options(*CHAR_LOAD_OPTS).where(Character.id == character_id)
    )
    return result.scalars().first()


@router.delete("/api/characters/{character_id}", status_code=204)
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Character).where(Character.id == character_id))
    char = result.scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    await delete_entity_references(db, "character", character_id)
    await db.delete(char)
    await db.commit()

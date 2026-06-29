from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from database import get_db, Character, Project
from schemas.schemas import CharacterCreate, CharacterUpdate, CharacterResponse

router = APIRouter()


@router.get("/api/projects/{project_id}/characters", response_model=List[CharacterResponse])
async def list_characters(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Character)
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
        reference_url=data.reference_url,
    )
    db.add(char)
    await db.commit()
    await db.refresh(char)
    return char


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
    if data.reference_url is not None:
        char.reference_url = data.reference_url

    await db.commit()
    await db.refresh(char)
    return char


@router.delete("/api/characters/{character_id}", status_code=204)
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Character).where(Character.id == character_id))
    char = result.scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    await db.delete(char)
    await db.commit()

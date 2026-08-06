import os

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Character, Project, Reference
from schemas.schemas import CharacterCreate, CharacterUpdate, CharacterResponse
from services.reference_service import delete_entity_references
from services import sheet_service

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

    # Shim: if reference_url provided, add it as a pool reference. No global
    # primary — a scene picks its own source of truth per scene_X.reference_id.
    if data.reference_url:
        ref = Reference(
            entity_type="character",
            entity_id=char.id,
            role="moodboard",
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

    # Shim: if reference_url provided, add a new pool reference. No global
    # primary to upsert in place — CharacterResponse.reference_url derives
    # from the newest reference, so this naturally becomes "the" one shown.
    if data.reference_url is not None:
        db.add(Reference(
            entity_type="character",
            entity_id=character_id,
            role="moodboard",
            url=data.reference_url,
        ))

    await db.commit()

    result = await db.execute(
        select(Character).options(*CHAR_LOAD_OPTS).where(Character.id == character_id)
    )
    return result.scalars().first()


@router.post("/api/characters/{character_id}/sheet", status_code=202)
async def create_character_sheet(character_id: str, data: dict = Body(default={}),
                                 db: AsyncSession = Depends(get_db)):
    """Generate a character sheet: a batch of consistent angles/expressions/
    wardrobe cells sharing a locked seed (KAN-38). Optional body ``cells`` (list
    of {slot, suffix}) overrides the default grid."""
    char = (await db.execute(
        select(Character).where(Character.id == character_id)
    )).scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        batch, jobs = await sheet_service.create_character_sheet(
            char, db, cells=data.get("cells"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"batch_id": batch.id, "job_count": len(jobs)}


@router.get("/api/characters/{character_id}/dataset.zip")
async def download_character_dataset(character_id: str, db: AsyncSession = Depends(get_db)):
    """Stream a LoRA-ready dataset zip (images + caption txts + metadata.json)
    of the character's sheet images (KAN-40). 404 when there are none."""
    char = (await db.execute(
        select(Character).where(Character.id == character_id)
    )).scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")

    tmp_path = await sheet_service.build_dataset_zip(char, db)
    if tmp_path is None:
        raise HTTPException(status_code=404, detail="Character has no sheet images")

    def _iter():
        try:
            with open(tmp_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        finally:
            os.unlink(tmp_path)

    filename = f"{char.name or 'character'}_dataset.zip".replace(" ", "_")
    return StreamingResponse(
        _iter(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/characters/{character_id}", status_code=204)
async def delete_character(character_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Character).where(Character.id == character_id))
    char = result.scalars().first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    await delete_entity_references(db, "character", character_id)
    await db.delete(char)
    await db.commit()

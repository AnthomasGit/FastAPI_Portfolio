from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Prop, Project
from schemas.schemas import PropCreate, PropUpdate, PropResponse
from services.reference_service import delete_entity_references
from services import sheet_service

router = APIRouter()


@router.get("/api/projects/{project_id}/props", response_model=List[PropResponse])
async def list_props(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Prop)
        # Eager-load: the response derives reference_url from the newest
        # reference, and a lazy load in async context raises MissingGreenlet.
        .options(selectinload(Prop.references))
        .where(Prop.project_id == project_id)
        .order_by(Prop.name)
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/props", status_code=201, response_model=PropResponse)
async def create_prop(project_id: str, data: PropCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    prop = Prop(
        project_id=project_id,
        name=data.name,
        description=data.description,
    )
    db.add(prop)
    await db.commit()
    await db.refresh(prop)
    return prop


@router.put("/api/props/{prop_id}", response_model=PropResponse)
async def update_prop(prop_id: str, data: PropUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prop).where(Prop.id == prop_id))
    prop = result.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")

    if data.name is not None:
        prop.name = data.name
    if data.description is not None:
        prop.description = data.description

    await db.commit()
    await db.refresh(prop)
    return prop


@router.delete("/api/props/{prop_id}", status_code=204)
async def delete_prop(prop_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prop).where(Prop.id == prop_id))
    prop = result.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    await delete_entity_references(db, "prop", prop_id)
    await db.delete(prop)
    await db.commit()


@router.post("/api/props/{prop_id}/sheet", status_code=202)
async def create_prop_sheet(prop_id: str, data: dict = Body(default={}),
                            db: AsyncSession = Depends(get_db)):
    """Generate a prop sheet: consistent angles plus a top-down and a material
    close-up, sharing a locked seed. No expression cells — a prop has no face.

    Optional body: ``cells`` overrides the grid, ``workflow`` picks the txt2img
    model, and ``from_canonical`` (default true) chooses img2img off the prop's
    canonical image versus a fresh render.
    """
    prop = (await db.execute(select(Prop).where(Prop.id == prop_id))).scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    try:
        batch, jobs = await sheet_service.create_entity_sheet(
            prop, "prop", db, cells=data.get("cells"),
            workflow=data.get("workflow"),
            from_canonical=bool(data.get("from_canonical", True)),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"batch_id": batch.id, "job_count": len(jobs)}

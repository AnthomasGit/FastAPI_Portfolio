from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from database import get_db, Location, Project
from schemas.schemas import LocationCreate, LocationUpdate, LocationResponse

router = APIRouter()


@router.get("/api/projects/{project_id}/locations", response_model=List[LocationResponse])
async def list_locations(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Location)
        .where(Location.project_id == project_id)
        .order_by(Location.name)
    )
    return result.scalars().all()


@router.post("/api/projects/{project_id}/locations", status_code=201, response_model=LocationResponse)
async def create_location(project_id: str, data: LocationCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    loc = Location(
        project_id=project_id,
        name=data.name,
        description=data.description,
        shot_notes=data.shot_notes,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@router.put("/api/locations/{location_id}", response_model=LocationResponse)
async def update_location(location_id: str, data: LocationUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Location).where(Location.id == location_id))
    loc = result.scalars().first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    if data.name is not None:
        loc.name = data.name
    if data.description is not None:
        loc.description = data.description
    if data.shot_notes is not None:
        loc.shot_notes = data.shot_notes

    await db.commit()
    await db.refresh(loc)
    return loc


@router.delete("/api/locations/{location_id}", status_code=204)
async def delete_location(location_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Location).where(Location.id == location_id))
    loc = result.scalars().first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    await db.delete(loc)
    await db.commit()

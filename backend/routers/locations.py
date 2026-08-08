from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from database import get_db, Location, Project
from schemas.schemas import LocationCreate, LocationUpdate, LocationResponse
from services.reference_service import delete_entity_references
from services import plate_service

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


@router.post("/api/locations/{location_id}/plate", status_code=202)
async def generate_plate(location_id: str, data: dict = Body(default={}),
                         db: AsyncSession = Depends(get_db)):
    """Generate a wide, character-free establishing plate for this location
    (KAN-41). Optional body: width, height, workflow. On completion the job
    sets the location's plate_asset_image_id."""
    loc = (await db.execute(select(Location).where(Location.id == location_id))).scalars().first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    asset_id = await plate_service.generate_location_plate(
        loc, db,
        width=data.get("width"),
        height=data.get("height"),
        workflow=data.get("workflow"),
    )
    return {"asset_image_id": asset_id}


@router.post("/api/locations/{location_id}/plate/expand", status_code=202)
async def expand_plate(location_id: str, data: dict = Body(default={}),
                       db: AsyncSession = Depends(get_db)):
    """Widen this location's plate via an outpaint pass (KAN-43). Body: a
    ``preset`` ("widen_21_9" | "pan_left" | "pan_right") and/or explicit
    ``expand_left|right|top|bottom`` pixel amounts, optional ``prompt``. The
    result is a new AssetImage linked back to the source plate."""
    loc = (await db.execute(select(Location).where(Location.id == location_id))).scalars().first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    try:
        asset_id = await plate_service.expand_location_plate(
            loc, db,
            preset=data.get("preset"),
            amounts=data,
            prompt=data.get("prompt"),
        )
    except ValueError as e:
        # No plate → 404; bad/empty expansion → 422.
        if "no plate" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e)) from e
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"asset_image_id": asset_id}


@router.delete("/api/locations/{location_id}", status_code=204)
async def delete_location(location_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Location).where(Location.id == location_id))
    loc = result.scalars().first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    await delete_entity_references(db, "location", location_id)
    await db.delete(loc)
    await db.commit()

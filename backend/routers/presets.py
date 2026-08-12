"""Batch preset endpoints (KAN-48)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.schemas import PresetCreate, PresetUpdate, PresetRun
from services.batch_service import BatchValidationError, InsufficientDiskError
from services import preset_service

router = APIRouter()


async def _require(preset_id: str, db: AsyncSession):
    preset = await preset_service.get_preset(preset_id, db)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.post("/api/presets", status_code=201)
async def create(data: PresetCreate, db: AsyncSession = Depends(get_db)):
    preset = await preset_service.create_preset(data.name, data.spec, data.project_id, db)
    return preset_service.serialize(preset)


@router.get("/api/presets")
async def list_all(project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    presets = await preset_service.list_presets(project_id, db)
    return [preset_service.serialize(p) for p in presets]


@router.get("/api/presets/{preset_id}")
async def get_one(preset_id: str, db: AsyncSession = Depends(get_db)):
    return preset_service.serialize(await _require(preset_id, db))


@router.put("/api/presets/{preset_id}")
async def update(preset_id: str, data: PresetUpdate, db: AsyncSession = Depends(get_db)):
    preset = await _require(preset_id, db)
    preset = await preset_service.update_preset(preset, data.name, data.spec, db)
    return preset_service.serialize(preset)


@router.delete("/api/presets/{preset_id}", status_code=204)
async def delete(preset_id: str, db: AsyncSession = Depends(get_db)):
    await preset_service.delete_preset(await _require(preset_id, db), db)


@router.post("/api/presets/{preset_id}/run", status_code=201)
async def run(preset_id: str, data: PresetRun, db: AsyncSession = Depends(get_db)):
    preset = await _require(preset_id, db)
    try:
        return await preset_service.run_preset(preset, data.overrides, db)
    except InsufficientDiskError as e:
        raise HTTPException(status_code=507, detail=str(e)) from e
    except ValueError as e:  # BatchValidationError + create_batch ValueErrors
        raise HTTPException(status_code=422, detail=str(e)) from e

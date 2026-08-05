from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Project, Batch
from schemas.schemas import BatchCreateRequest
from services.batch_service import (
    create_batch,
    batch_summary,
    cancel_batch,
    retry_failed,
    list_project_batches,
    VALID_SCOPES,
)

router = APIRouter()


async def _get_batch(batch_id: str, db: AsyncSession) -> Batch:
    batch = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalars().first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.post("/api/batches", status_code=201)
async def create_batch_endpoint(
    data: BatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid scope '{data.scope}'. Must be one of: {', '.join(sorted(VALID_SCOPES))}",
        )

    if not (await db.execute(select(Project).where(Project.id == data.project_id))).scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    batch, jobs = await create_batch(data.model_dump(), db)
    return {"batch_id": batch.id, "job_count": len(jobs)}


@router.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await _get_batch(batch_id, db)
    return await batch_summary(batch, db)


@router.get("/api/projects/{project_id}/batches")
async def list_batches(project_id: str, db: AsyncSession = Depends(get_db)):
    if not (await db.execute(select(Project).where(Project.id == project_id))).scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")
    return await list_project_batches(project_id, db)


@router.post("/api/batches/{batch_id}/cancel")
async def cancel(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await _get_batch(batch_id, db)
    return await cancel_batch(batch, db)


@router.post("/api/batches/{batch_id}/retry-failed")
async def retry(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await _get_batch(batch_id, db)
    return await retry_failed(batch, db)

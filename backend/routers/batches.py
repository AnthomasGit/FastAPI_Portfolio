from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Project
from schemas.schemas import BatchCreateRequest
from services.batch_service import create_batch, VALID_SCOPES

router = APIRouter()


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

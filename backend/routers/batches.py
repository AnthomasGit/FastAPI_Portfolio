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
    estimate_output_bytes,
    free_output_bytes,
    parse_run_after,
    DISK_SAFETY_MARGIN,
    VALID_SCOPES,
)
from services.workflow_registry import validate_params

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

    spec = data.model_dump()

    # Reject a spec whose params name a knob the chosen workflow can't route,
    # so an unroutable override fails here rather than silently no-op'ing in
    # inject() and producing a plausible-but-wrong render (KAN-45).
    unknown = validate_params(data.kind, data.workflow, spec.get("params") or {})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown workflow param(s) for kind '{data.kind}': "
                f"{', '.join(sorted(unknown))}."
            ),
        )

    # Fail fast on a bad run_after before doing any work.
    try:
        parse_run_after(spec.get("run_after"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Refuse an overnight batch that would likely fill the output disk.
    estimated_bytes, _ = await estimate_output_bytes(spec, db)
    free = free_output_bytes()
    if estimated_bytes * DISK_SAFETY_MARGIN > free:
        raise HTTPException(
            status_code=507,
            detail=(
                f"Estimated output {estimated_bytes} bytes needs "
                f"{DISK_SAFETY_MARGIN}x free space; only {free} bytes free on the output disk."
            ),
        )

    try:
        batch, jobs = await create_batch(spec, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "batch_id": batch.id,
        "job_count": len(jobs),
        "estimated_output_bytes": estimated_bytes,
    }


@router.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await _get_batch(batch_id, db)
    return await batch_summary(batch, db, include_jobs=True)


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

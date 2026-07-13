from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Asset3D, Project, Character, Prop, Reference
from schemas.schemas import Asset3DMeshGenerateRequest, Asset3DResponse
from services.asset3d_service import trigger_mesh, poll_asset, retry_mesh, get_mesh_file, delete_asset
from services.reference_service import get_entity

router = APIRouter()

VALID_ENTITY_TYPES = {"character", "prop"}


@router.post("/api/assets3d/generate", status_code=202)
async def generate_asset3d(
    data: Asset3DMeshGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.entity_type == "location":
        raise HTTPException(
            status_code=422,
            detail="Mesh generation is not supported for locations",
        )

    if data.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid entity_type: {data.entity_type}. Must be one of: character, prop",
        )

    entity = await get_entity(db, data.entity_type, data.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{data.entity_type} not found")

    project_id = entity.project_id

    try:
        asset_id, warning = await trigger_mesh(
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            project_id=project_id,
            db=db,
            reference_id=data.reference_id,
            params=data.params,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = {"asset3d_id": asset_id}
    if warning:
        result["warning"] = warning
    return result


@router.get("/api/assets3d/{asset3d_id}", response_model=Asset3DResponse)
async def get_asset3d(asset3d_id: str, db: AsyncSession = Depends(get_db)):
    asset = await poll_asset(asset3d_id, db)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset3D not found")
    return asset


@router.get("/api/projects/{project_id}/assets3d", response_model=List[Asset3DResponse])
async def list_assets3d(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    assets = await db.execute(
        select(Asset3D)
        .where(Asset3D.project_id == project_id)
        .order_by(Asset3D.created_at.desc())
    )
    return assets.scalars().all()


@router.post("/api/assets3d/{asset3d_id}/retry", status_code=202)
async def retry_asset3d(asset3d_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await retry_mesh(asset3d_id, db)
    except ValueError as e:
        raise HTTPException(status_code=409 if "status" in str(e) else 404, detail=str(e))

    return {"asset3d_id": asset3d_id}


@router.get("/api/assets3d/{asset3d_id}/mesh")
async def get_asset3d_mesh(
    asset3d_id: str,
    rigged: bool = False,
    db: AsyncSession = Depends(get_db),
):
    content = await get_mesh_file(asset3d_id, db, rigged=rigged)
    if content is None:
        raise HTTPException(status_code=404, detail="Mesh file not found")

    return Response(content=content, media_type="model/gltf-binary")


@router.delete("/api/assets3d/{asset3d_id}", status_code=204)
async def delete_asset3d(asset3d_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await delete_asset(asset3d_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset3D not found")

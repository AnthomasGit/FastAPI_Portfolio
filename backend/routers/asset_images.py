from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List, Optional

from database import get_db, AssetImage, Reference, Project, Character, Location, Prop
from schemas.schemas import (
    AssetImageGenerateRequest,
    AssetImageResponse,
    AssetImageAssignRequest,
    ReferenceResponse,
)
from services.asset_image_service import (
    generate_txt2img,
    generate_img2img,
    poll_asset_image_status,
    get_asset_image_file,
)
from services.reference_service import enforce_single_primary

router = APIRouter()

VALID_ENTITY_TYPES = {"characters", "locations", "props"}
ENTITY_TABLE_MAP = {
    "characters": Character,
    "locations": Location,
    "props": Prop,
}
PLURAL_TO_SINGULAR = {
    "characters": "character",
    "locations": "location",
    "props": "prop",
}


@router.post("/api/asset-images/generate", status_code=202)
async def trigger_asset_image_generation(
    data: AssetImageGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid entity_type: {data.entity_type}. Must be one of: {', '.join(VALID_ENTITY_TYPES)}",
        )

    result = await db.execute(select(Project).where(Project.id == data.project_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail="Project not found")

    if data.source_reference_id or data.source_asset_image_id:
        asset_id = await generate_img2img(
            project_id=data.project_id,
            entity_type=PLURAL_TO_SINGULAR[data.entity_type],
            prompt=data.prompt or "",
            db=db,
            source_reference_id=data.source_reference_id,
            source_asset_image_id=data.source_asset_image_id,
        )
    else:
        if not data.prompt:
            raise HTTPException(status_code=422, detail="prompt is required for txt2img generation")
        asset_id = await generate_txt2img(
            project_id=data.project_id,
            entity_type=PLURAL_TO_SINGULAR[data.entity_type],
            prompt=data.prompt,
            db=db,
        )

    return {"asset_image_id": asset_id}


@router.get("/api/asset-images", response_model=List[AssetImageResponse])
async def list_asset_images(
    entity_type: Optional[str] = None,
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AssetImage).order_by(AssetImage.created_at.desc())

    if entity_type:
        if entity_type not in VALID_ENTITY_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid entity_type: {entity_type}",
            )
        query = query.where(AssetImage.entity_type == PLURAL_TO_SINGULAR[entity_type])

    if project_id:
        query = query.where(AssetImage.origin_project_id == project_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/api/asset-images/{asset_image_id}", response_model=AssetImageResponse)
async def get_asset_image(asset_image_id: str, db: AsyncSession = Depends(get_db)):
    result = await poll_asset_image_status(asset_image_id, db)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Asset image not found")

    asset_result = await db.execute(
        select(AssetImage).where(AssetImage.id == asset_image_id)
    )
    asset = asset_result.scalars().first()
    return asset


@router.get("/api/asset-images/{asset_image_id}/file")
async def get_asset_image_file_proxy(asset_image_id: str, db: AsyncSession = Depends(get_db)):
    try:
        content = await get_asset_image_file(asset_image_id, db)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found: {str(e)}")

    if content is None:
        raise HTTPException(status_code=404, detail="Asset image or file not found")

    return Response(content=content, media_type="image/png")


@router.post("/api/{entity_type}/{entity_id}/assign-asset", response_model=ReferenceResponse)
async def assign_asset_image(
    entity_type: str,
    entity_id: str,
    data: AssetImageAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid entity_type: {entity_type}",
        )

    singular = PLURAL_TO_SINGULAR[entity_type]
    table = ENTITY_TABLE_MAP[entity_type]
    result = await db.execute(select(table).where(table.id == entity_id))
    if not result.scalars().first():
        raise HTTPException(status_code=404, detail=f"{singular} not found")

    asset_result = await db.execute(
        select(AssetImage).where(AssetImage.id == data.asset_image_id)
    )
    asset = asset_result.scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset image not found")
    if asset.status != "completed" or not asset.image_url:
        raise HTTPException(
            status_code=422,
            detail="Asset image is not completed yet",
        )

    existing = await db.execute(
        select(Reference).where(
            Reference.entity_type == singular,
            Reference.entity_id == entity_id,
            Reference.role == "primary",
        )
    )
    ref = existing.scalars().first()

    if ref:
        ref.url = asset.image_url
        ref.asset_image_id = asset.id
    else:
        ref = Reference(
            entity_type=singular,
            entity_id=entity_id,
            role="primary",
            url=asset.image_url,
            asset_image_id=asset.id,
        )
        db.add(ref)

    await db.flush()
    await enforce_single_primary(db, singular, entity_id, ref.id)
    await db.commit()
    await db.refresh(ref)
    return ref

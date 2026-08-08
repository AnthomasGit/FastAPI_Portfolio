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
    ImageWorkflowResponse,
    ReferenceResponse,
)
from services.asset_image_service import (
    generate_txt2img,
    generate_img2img,
    poll_asset_image_status,
    get_asset_image_file,
)
from services.image_workflows import list_image_workflows
from services.prompt_builder import location_prompt

router = APIRouter()


@router.get("/api/image-workflows", response_model=List[ImageWorkflowResponse])
async def get_image_workflows():
    """Selectable txt2img models for the asset-image generator's model picker."""
    return list_image_workflows()

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

    # Attach the location's fixed profile tokens to the prompt so location
    # renders stay consistent (KAN-41). Only for locations, only when the
    # generator names which one (entity_id).
    prompt = data.prompt
    if data.entity_type == "locations" and data.entity_id:
        loc = await db.get(Location, data.entity_id)
        if loc is not None:
            tokens = location_prompt(loc)
            prompt = f"{tokens}. {prompt}" if prompt else tokens

    if data.source_reference_id or data.source_asset_image_id:
        asset_id = await generate_img2img(
            project_id=data.project_id,
            entity_type=PLURAL_TO_SINGULAR[data.entity_type],
            prompt=prompt or "",
            db=db,
            source_reference_id=data.source_reference_id,
            source_asset_image_id=data.source_asset_image_id,
        )
    else:
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt is required for txt2img generation")
        asset_id = await generate_txt2img(
            project_id=data.project_id,
            entity_type=PLURAL_TO_SINGULAR[data.entity_type],
            prompt=prompt,
            db=db,
            width=data.width,
            height=data.height,
            workflow=data.workflow,
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

    # A pool reference, not a global primary — there is no entity-level
    # primary. Find-or-create by asset_image_id so re-assigning the same
    # generated image doesn't pile up duplicate pool rows. The caller (Scene
    # Detail) is responsible for setting this as the current scene's primary
    # via PUT .../links/{entity_type}/{entity_id}.
    existing = await db.execute(
        select(Reference).where(
            Reference.entity_type == singular,
            Reference.entity_id == entity_id,
            Reference.asset_image_id == asset.id,
        )
    )
    ref = existing.scalars().first()

    if ref:
        ref.url = asset.image_url
    else:
        ref = Reference(
            entity_type=singular,
            entity_id=entity_id,
            role="moodboard",
            url=asset.image_url,
            asset_image_id=asset.id,
        )
        db.add(ref)

    await db.commit()
    await db.refresh(ref)
    return ref

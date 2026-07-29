import os
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List

from database import get_db, Reference, Scene, Character, Location, Prop
from schemas.schemas import ReferenceCreate, ReferenceUpdate, ReferenceResponse
from services.preprocess_service import remove_background
from services.reference_service import get_entity

router = APIRouter()

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

PLURAL_TO_SINGULAR = {
    "scenes": "scene",
    "characters": "character",
    "locations": "location",
    "props": "prop",
}
VALID_ENTITY_TYPES = set(PLURAL_TO_SINGULAR.keys())

ENTITY_LOAD_OPTS = {
    "scene": selectinload(Scene.references),
    "character": selectinload(Character.references),
    "location": selectinload(Location.references),
    "prop": selectinload(Prop.references),
}


@router.post("/api/uploads")
async def upload_file(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="File must be an image")

    ext = Path(file.filename).suffix if file.filename else ".png"
    if not ext:
        ext = ".png"
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(COMFY_INPUT_DIR, filename)

    contents = await file.read()
    try:
        img = Image.open(BytesIO(contents))
        img.verify()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid image file")

    with open(filepath, "wb") as f:
        f.write(contents)

    return {"url": filename}


@router.get("/api/{entity_type}/{entity_id}/references", response_model=List[ReferenceResponse])
async def list_references(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)):
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type: {entity_type}")

    result = await db.execute(
        select(Reference)
        .where(
            Reference.entity_type == PLURAL_TO_SINGULAR[entity_type],
            Reference.entity_id == entity_id,
        )
        .order_by(Reference.sort_order)
    )
    return result.scalars().all()


@router.post("/api/{entity_type}/{entity_id}/references", status_code=201, response_model=ReferenceResponse)
async def create_reference(
    entity_type: str, entity_id: str, data: ReferenceCreate, db: AsyncSession = Depends(get_db)
):
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type: {entity_type}")

    singular = PLURAL_TO_SINGULAR[entity_type]
    entity = await get_entity(db, singular, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{singular} not found")

    ref = Reference(
        entity_type=singular,
        entity_id=entity_id,
        role=data.role,
        url=data.url,
        description=data.description,
    )
    db.add(ref)
    await db.commit()
    await db.refresh(ref)
    return ref


@router.put("/api/references/{reference_id}", response_model=ReferenceResponse)
async def update_reference(reference_id: str, data: ReferenceUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reference).where(Reference.id == reference_id))
    ref = result.scalars().first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")

    if data.role is not None:
        ref.role = data.role
    if data.description is not None:
        ref.description = data.description
    if data.sort_order is not None:
        ref.sort_order = data.sort_order

    await db.commit()
    await db.refresh(ref)
    return ref


@router.delete("/api/references/{reference_id}", status_code=204)
async def delete_reference(reference_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reference).where(Reference.id == reference_id))
    ref = result.scalars().first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    await db.delete(ref)
    await db.commit()


@router.post("/api/references/{reference_id}/remove-background", response_model=ReferenceResponse)
async def remove_background_from_reference(
    reference_id: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Reference).where(Reference.id == reference_id))
    ref = result.scalars().first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    if not ref.url:
        raise HTTPException(status_code=422, detail="Reference has no url to process")

    input_path = os.path.join(COMFY_INPUT_DIR, ref.url)
    if not os.path.exists(input_path) and "/" in ref.url:
        input_path = os.path.join(COMFY_OUTPUT_DIR, ref.url)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=422, detail="Reference image file not found on disk")

    try:
        processed_filename = await remove_background(input_path, COMFY_INPUT_DIR)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {str(e)}")

    ref.processed_url = processed_filename
    await db.commit()
    await db.refresh(ref)
    return ref


@router.delete("/api/references/{reference_id}/remove-background", response_model=ReferenceResponse)
async def restore_background_on_reference(
    reference_id: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Reference).where(Reference.id == reference_id))
    ref = result.scalars().first()
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")

    if ref.processed_url:
        processed_path = os.path.join(COMFY_INPUT_DIR, ref.processed_url)
        try:
            os.unlink(processed_path)
        except OSError:
            pass  # best-effort cleanup; file may already be gone
        ref.processed_url = None
        await db.commit()
        await db.refresh(ref)
    return ref

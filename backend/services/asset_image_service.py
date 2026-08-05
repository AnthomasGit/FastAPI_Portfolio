import os
import uuid
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage
from services.comfyui_client import submit, poll
from services.job_handlers import (
    HANDLERS,
    _resolve_source_image,  # re-exported for backward compatibility
)

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

TXT2IMG_WORKFLOW = "image_z_image_turbo"
IMG2IMG_WORKFLOW = "image_flux2_klein_image_edit_4b_base"


async def generate_txt2img(
    project_id: str,
    entity_type: str,
    prompt: str,
    db: AsyncSession,
    width: int | None = None,
    height: int | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    seed_val = random.randint(1, 1000000000000000)

    asset = AssetImage(
        origin_project_id=project_id,
        entity_type=entity_type,
        kind="txt2img",
        prompt=prompt,
        status="queued",
        job_id=job_id,
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    try:
        workflow, meta = await HANDLERS["asset_txt2img"].build_workflow(
            {
                "project_id": project_id,
                "entity_type": entity_type,
                "prompt": prompt,
                "width": width,
                "height": height,
                "job_id": job_id,
                "seed": seed_val,
            },
            db,
        )

        prompt_id = await submit(workflow)

        asset.status = "processing"
        asset.prompt_id = prompt_id
        asset.image_url = meta["image_url"]
        await db.commit()

    except Exception as e:
        asset.status = "failed"
        asset.error = str(e)
        await db.commit()

    return asset_id


async def generate_img2img(
    project_id: str,
    entity_type: str,
    prompt: str,
    db: AsyncSession,
    source_reference_id: str | None = None,
    source_asset_image_id: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    seed_val = random.randint(1, 1000000000000000)

    asset = AssetImage(
        origin_project_id=project_id,
        entity_type=entity_type,
        kind="img2img",
        prompt=prompt,
        status="queued",
        job_id=job_id,
        source_reference_id=source_reference_id,
        source_asset_image_id=source_asset_image_id,
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    try:
        workflow, meta = await HANDLERS["asset_img2img"].build_workflow(
            {
                "project_id": project_id,
                "entity_type": entity_type,
                "prompt": prompt,
                "source_reference_id": source_reference_id,
                "source_asset_image_id": source_asset_image_id,
                "job_id": job_id,
                "seed": seed_val,
            },
            db,
        )

        prompt_id = await submit(workflow)

        asset.status = "processing"
        asset.prompt_id = prompt_id
        asset.image_url = meta["image_url"]
        await db.commit()

    except Exception as e:
        asset.status = "failed"
        asset.error = str(e)
        await db.commit()

    return asset_id


async def poll_asset_image_status(asset_id: str, db: AsyncSession) -> dict:
    result = await db.execute(select(AssetImage).where(AssetImage.id == asset_id))
    asset = result.scalars().first()
    if not asset:
        return {"status": "not_found"}

    if asset.status in ("completed", "failed"):
        return {"id": asset.id, "status": asset.status, "image_url": asset.image_url}

    if asset.prompt_id:
        result = await poll(asset.prompt_id)
        if result["status"] == "error":
            asset.status = "failed"
            asset.error = "ComfyUI reported an error"
            await db.commit()
            return {"id": asset.id, "status": "failed"}
        elif result["status"] == "completed":
            asset.status = "completed"
            await db.commit()
            return {"id": asset.id, "status": "completed", "image_url": asset.image_url}

    return {"id": asset.id, "status": asset.status}


async def get_asset_image_file(asset_id: str, db: AsyncSession) -> bytes | None:
    result = await db.execute(select(AssetImage).where(AssetImage.id == asset_id))
    asset = result.scalars().first()
    if not asset or not asset.image_url:
        return None

    filepath = os.path.join(COMFY_OUTPUT_DIR, asset.image_url)
    try:
        with open(filepath, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None

import os
import uuid
import random
import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, Reference
from services.comfyui_client import load_workflow, load_node_map, inject, submit, poll

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
    prefix = f"assets/{project_id}/{entity_type}s/{job_id}"

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
        workflow = load_workflow(TXT2IMG_WORKFLOW)
        node_map = load_node_map(TXT2IMG_WORKFLOW)

        overrides = {
            "prompt": prompt,
            "seed": seed_val,
            "filename_prefix": prefix,
        }
        if width is not None:
            overrides["width"] = width
        if height is not None:
            overrides["height"] = height

        workflow = inject(workflow, node_map, overrides)

        prompt_id = await submit(workflow)

        asset.status = "processing"
        asset.prompt_id = prompt_id
        asset.image_url = f"assets/{project_id}/{entity_type}s/{job_id}_00001_.png"
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
    prefix = f"assets/{project_id}/{entity_type}s/{job_id}"

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
        source_filename = await _resolve_source_image(
            db, source_reference_id, source_asset_image_id, job_id
        )
        if not source_filename:
            raise ValueError("No source image provided for img2img")

        workflow = load_workflow(IMG2IMG_WORKFLOW)
        node_map = load_node_map(IMG2IMG_WORKFLOW)

        workflow = inject(workflow, node_map, {
            "prompt": prompt,
            "seed": seed_val,
            "image": source_filename,
            "filename_prefix": prefix,
        })

        prompt_id = await submit(workflow)

        asset.status = "processing"
        asset.prompt_id = prompt_id
        asset.image_url = f"assets/{project_id}/{entity_type}s/{job_id}_00001_.png"
        await db.commit()

    except Exception as e:
        asset.status = "failed"
        asset.error = str(e)
        await db.commit()

    return asset_id


async def _resolve_source_image(
    db: AsyncSession,
    source_reference_id: str | None,
    source_asset_image_id: str | None,
    job_id: str,
) -> str | None:
    if source_reference_id:
        result = await db.execute(select(Reference).where(Reference.id == source_reference_id))
        ref = result.scalars().first()
        if not ref:
            raise ValueError("Source reference not found")
        source_filename = ref.processed_url or ref.url
        if ref.asset_image_id and source_filename and "/" in source_filename:
            src_path = os.path.join(COMFY_OUTPUT_DIR, source_filename)
            input_filename = f"{job_id}_source.png"
            dst_path = os.path.join(COMFY_INPUT_DIR, input_filename)
            shutil.copy2(src_path, dst_path)
            return input_filename
        return source_filename

    if source_asset_image_id:
        result = await db.execute(select(AssetImage).where(AssetImage.id == source_asset_image_id))
        asset = result.scalars().first()
        if not asset or not asset.image_url:
            raise ValueError("Source asset image not found or not ready")
        src_path = os.path.join(COMFY_OUTPUT_DIR, asset.image_url)
        input_filename = f"{job_id}_source.png"
        dst_path = os.path.join(COMFY_INPUT_DIR, input_filename)
        shutil.copy2(src_path, dst_path)
        return input_filename

    return None


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

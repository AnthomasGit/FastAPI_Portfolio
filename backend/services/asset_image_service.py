import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, JobRecord
from services.job_handlers import (
    frontend_status,
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
    workflow: str | None = None,
) -> str:
    """Enqueue a txt2img job and return immediately; the worker submits it.

    ``workflow`` selects the ComfyUI graph from image_workflows.IMAGE_WORKFLOWS
    (None -> default). It rides in the job payload and is resolved to a graph
    name by build_asset_txt2img.
    """
    asset = AssetImage(
        origin_project_id=project_id,
        entity_type=entity_type,
        kind="txt2img",
        prompt=prompt,
        status="queued",
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    # No job_id in the payload — the worker mints a fresh output prefix per
    # attempt (idempotent retry, KAN-21).
    job = JobRecord(
        kind="asset_txt2img",
        status="queued",
        entity_type="asset_image",
        entity_id=asset_id,
        payload={
            "project_id": project_id,
            "entity_type": entity_type,
            "prompt": prompt,
            "width": width,
            "height": height,
            "workflow": workflow,
            "asset_image_id": asset_id,
        },
    )
    db.add(job)
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
    """Enqueue an img2img job and return immediately; the worker submits it."""
    asset = AssetImage(
        origin_project_id=project_id,
        entity_type=entity_type,
        kind="img2img",
        prompt=prompt,
        status="queued",
        source_reference_id=source_reference_id,
        source_asset_image_id=source_asset_image_id,
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    job = JobRecord(
        kind="asset_img2img",
        status="queued",
        entity_type="asset_image",
        entity_id=asset_id,
        payload={
            "project_id": project_id,
            "entity_type": entity_type,
            "prompt": prompt,
            "source_reference_id": source_reference_id,
            "source_asset_image_id": source_asset_image_id,
            "asset_image_id": asset_id,
        },
    )
    db.add(job)
    await db.commit()

    return asset_id


async def poll_asset_image_status(asset_id: str, db: AsyncSession) -> dict:
    """Reflect the owning job's state onto the AssetImage row (the asset-image
    endpoint returns the row itself), without driving progress — the worker
    owns that. Keeps the queued/processing/completed/failed strings intact."""
    asset = (
        await db.execute(select(AssetImage).where(AssetImage.id == asset_id))
    ).scalars().first()
    if not asset:
        return {"status": "not_found"}

    if asset.status in ("completed", "failed"):
        return {"id": asset.id, "status": asset.status, "image_url": asset.image_url}

    job = (
        await db.execute(
            select(JobRecord)
            .where(JobRecord.entity_type == "asset_image",
                   JobRecord.entity_id == asset_id)
            .order_by(JobRecord.created_at.desc())
        )
    ).scalars().first()

    if job is not None:
        mapped = frontend_status(job.status)
        if asset.status != mapped:
            asset.status = mapped
            if mapped == "failed":
                asset.error = job.error
            await db.commit()
        return {"id": asset.id, "status": mapped, "image_url": asset.image_url}

    return {"id": asset.id, "status": asset.status, "image_url": asset.image_url}


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

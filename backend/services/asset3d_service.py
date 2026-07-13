import os
import uuid
import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset3D, JobRecord, Reference, Project
from services.comfyui_client import load_workflow, load_node_map, inject, submit, poll
from services.preprocess_service import remove_background

MESH_WORKFLOW = "mesh_hunyuan3d_21"
COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
MESH_TIMEOUT_MINUTES = 30


async def _resolve_reference(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
    reference_id: str | None = None,
) -> tuple[Reference | None, str | None]:
    if reference_id:
        result = await db.execute(select(Reference).where(Reference.id == reference_id))
        ref = result.scalars().first()
        if not ref:
            raise ValueError("Reference not found")
        warning = None
        if ref.asset_image_id:
            warning = "Generated image — mesh quality may suffer; prefer a T-pose photo"
        return ref, warning

    result = await db.execute(
        select(Reference)
        .where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
        )
        .order_by(Reference.sort_order)
    )
    refs = result.scalars().all()

    for role in ("tpose",):
        match = next((r for r in refs if r.role == role), None)
        if match:
            warning = None
            if match.asset_image_id:
                warning = "Generated image — mesh quality may suffer; prefer a T-pose photo"
            return match, warning

    uploaded = [r for r in refs if r.url and not r.asset_image_id and r.role != "primary"]
    if uploaded:
        return uploaded[0], None

    primary = next((r for r in refs if r.role == "primary"), None)
    if primary:
        warning = None
        if primary.asset_image_id:
            warning = "Generated image — mesh quality may suffer; prefer a T-pose photo"
        return primary, warning

    return None, None


async def trigger_mesh(
    entity_type: str,
    entity_id: str,
    project_id: str,
    db: AsyncSession,
    reference_id: str | None = None,
    params: dict | None = None,
) -> tuple[str, str | None]:
    if entity_type == "location":
        raise ValueError("Mesh generation is not supported for locations")

    ref, warning = await _resolve_reference(db, entity_type, entity_id, reference_id)
    if not ref:
        raise ValueError("No reference image found for this entity. Upload a photo first.")

    source_url = ref.processed_url or ref.url
    source_path = os.path.join(COMFY_INPUT_DIR, source_url)

    if not ref.processed_url:
        try:
            processed_filename = remove_background(source_path, COMFY_INPUT_DIR)
            ref.processed_url = processed_filename
            source_url = processed_filename
        except Exception:
            pass

    asset = Asset3D(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        source_reference_id=ref.id,
        status="queued",
        params=params or {},
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    job_id = str(uuid.uuid4())
    seed_val = params.get("seed", random.randint(1, 1000000000000000)) if params else random.randint(1, 1000000000000000)

    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=MESH_WORKFLOW,
        query=f"mesh/{entity_type}/{entity_id}",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset_id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(MESH_WORKFLOW)
        if workflow.get("_placeholder"):
            raise RuntimeError("Mesh workflow not yet configured — replace mesh_hunyuan3d_21.json with a real ComfyUI export")

        node_map = load_node_map(MESH_WORKFLOW)

        prefix = f"meshes/{project_id}/{entity_type}s/{job_id}"
        workflow = inject(workflow, node_map, {
            "image": source_url,
            "seed": seed_val,
            "filename_prefix": prefix,
        })

        prompt_id = await submit(workflow)

        asset.status = "mesh_processing"
        asset.mesh_job_id = job_id
        asset.params = {**(asset.params or {}), "seed": seed_val}
        asset.mesh_url = f"{prefix}.glb"

        job.prompt_id = prompt_id
        job.status = "processing"
        await db.commit()

    except Exception as e:
        asset.status = "mesh_failed"
        asset.error = str(e)
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.utcnow()
        await db.commit()

    return asset_id, warning


async def poll_asset(asset3d_id: str, db: AsyncSession) -> Asset3D | None:
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        return None

    if asset.status in ("mesh_ready", "mesh_failed", "rigged", "rig_failed"):
        return asset

    if asset.status == "queued":
        return asset

    if asset.status == "mesh_processing":
        if not asset.mesh_job_id:
            return asset

        job_result = await db.execute(select(JobRecord).where(JobRecord.job_id == asset.mesh_job_id))
        job = job_result.scalars().first()

        if job and job.created_at:
            elapsed = datetime.utcnow() - job.created_at
            if elapsed > timedelta(minutes=MESH_TIMEOUT_MINUTES):
                asset.status = "mesh_failed"
                asset.error = "Mesh generation timed out"
                if job:
                    job.status = "failed"
                    job.error = "Timed out"
                    job.finished_at = datetime.utcnow()
                await db.commit()
                return asset

        if job and job.prompt_id:
            poll_result = await poll(job.prompt_id)
            if poll_result["status"] == "error":
                asset.status = "mesh_failed"
                asset.error = "ComfyUI reported an error"
                job.status = "failed"
                job.error = "ComfyUI error"
                job.finished_at = datetime.utcnow()
                await db.commit()
            elif poll_result["status"] == "completed":
                asset.status = "mesh_ready"
                job.status = "completed"
                job.finished_at = datetime.utcnow()
                await db.commit()

        return asset

    return asset


async def retry_mesh(asset3d_id: str, db: AsyncSession) -> str:
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        raise ValueError("Asset3D not found")

    if asset.status != "mesh_failed":
        raise ValueError(f"Cannot retry asset in status '{asset.status}'. Only 'mesh_failed' can be retried.")

    ref_result = await db.execute(select(Reference).where(Reference.id == asset.source_reference_id))
    ref = ref_result.scalars().first()
    if not ref:
        raise ValueError("Source reference not found or was deleted")

    source_url = ref.processed_url or ref.url
    if not source_url:
        raise ValueError("Source reference has no image")

    job_id = str(uuid.uuid4())
    seed_val = random.randint(1, 1000000000000000)

    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=MESH_WORKFLOW,
        query=f"mesh/{asset.entity_type}/{asset.entity_id}/retry",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset.id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(MESH_WORKFLOW)
        if workflow.get("_placeholder"):
            raise RuntimeError("Mesh workflow not yet configured — replace mesh_hunyuan3d_21.json with a real ComfyUI export")

        node_map = load_node_map(MESH_WORKFLOW)

        prefix = f"meshes/{asset.project_id}/{asset.entity_type}s/{job_id}"
        workflow = inject(workflow, node_map, {
            "image": source_url,
            "seed": seed_val,
            "filename_prefix": prefix,
        })

        prompt_id = await submit(workflow)

        asset.status = "mesh_processing"
        asset.error = None
        asset.mesh_job_id = job_id
        asset.params = {**(asset.params or {}), "seed": seed_val}
        asset.mesh_url = f"{prefix}.glb"

        job.prompt_id = prompt_id
        job.status = "processing"
        await db.commit()

    except Exception as e:
        asset.status = "mesh_failed"
        asset.error = str(e)
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.utcnow()
        await db.commit()

    return asset.id


async def get_mesh_file(asset3d_id: str, db: AsyncSession, rigged: bool = False) -> bytes | None:
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        return None

    url = asset.rigged_mesh_url if rigged else asset.mesh_url
    if not url:
        return None

    filepath = os.path.join(COMFY_OUTPUT_DIR, url)
    try:
        with open(filepath, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


async def delete_asset(asset3d_id: str, db: AsyncSession) -> bool:
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        return False

    await db.delete(asset)
    await db.commit()
    return True

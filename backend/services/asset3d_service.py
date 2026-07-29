import glob
import os
import shutil
import uuid
import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset3D, JobRecord, Reference, Project
from services.comfyui_client import load_workflow, load_node_map, inject, submit, poll
from services.preprocess_service import remove_background

# Characters keep the dual-output Trellis2 workflow (textured + white/base
# mesh, the latter reusable for future per-scene re-texturing). Props (and
# set dressing, which rides the Prop entity) route to TripoSplat instead —
# much faster, but single-output and vertex-colored rather than textured;
# see bake_optimize.py for how that color survives web-optimization.
MESH_WORKFLOWS = {
    "character": {"workflow": "MeshWithTexturing_6steps_example", "dual_output": True},
    "prop": {"workflow": "3d_triposplat_image_to_gaussian_splat", "dual_output": False},
}
COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
MESH_TIMEOUT_MINUTES = 30
# Trellis2SparseGenerator's seed widget is a plain ComfyUI INT input
# (min=0, max=2147483647 — INT32), unlike Hunyuan3D's or TripoSplat's
# KSampler (uint64); clamp to the stricter bound so it's safe for both.
MAX_MESH_SEED = 2_147_483_647


async def _resolve_source_for_load(ref: Reference) -> str:
    """Return an INPUT-relative filename ComfyUI's LoadImage can read.

    Asset-image references are generated files that live in COMFY_OUTPUT_DIR
    under a subfolder (e.g. ``assets/<proj>/characters/<id>_00001_.png``);
    LoadImage only reads COMFY_INPUT_DIR, so stage a flat copy in first
    (mirrors asset_image_service._resolve_source_image). Then background-remove
    when the reference has not already been processed.
    """
    source_url = ref.processed_url or ref.url
    if ref.processed_url:
        return source_url

    if ref.asset_image_id and source_url and "/" in source_url:
        staged = f"{ref.id}_source.png"
        try:
            shutil.copy2(
                os.path.join(COMFY_OUTPUT_DIR, source_url),
                os.path.join(COMFY_INPUT_DIR, staged),
            )
        except OSError as e:
            raise ValueError(
                "Source image file is missing — regenerate the character image "
                "before creating a mesh"
            ) from e
        source_url = staged

    try:
        processed_filename = await remove_background(
            os.path.join(COMFY_INPUT_DIR, source_url), COMFY_INPUT_DIR
        )
        ref.processed_url = processed_filename
        return processed_filename
    except Exception:
        return source_url


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

    uploaded = [r for r in refs if r.url and not r.asset_image_id]
    if uploaded:
        return uploaded[0], None

    # No tpose, no uploaded photo — fall back to any reference (there is no
    # entity-level "primary" to prefer; that concept is per-scene only).
    fallback = next((r for r in refs if r.url), None)
    if fallback:
        warning = None
        if fallback.asset_image_id:
            warning = "Generated image — mesh quality may suffer; prefer a T-pose photo"
        return fallback, warning

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

    workflow_name = MESH_WORKFLOWS[entity_type]["workflow"]

    ref, warning = await _resolve_reference(db, entity_type, entity_id, reference_id)
    if not ref:
        raise ValueError("No reference image found for this entity. Upload a photo first.")

    source_url = await _resolve_source_for_load(ref)

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
    seed_val = params.get("seed", random.randint(1, MAX_MESH_SEED)) if params else random.randint(1, MAX_MESH_SEED)

    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=workflow_name,
        query=f"mesh/{entity_type}/{entity_id}",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset_id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(workflow_name)
        if workflow.get("_placeholder"):
            raise RuntimeError(f"Mesh workflow not yet configured — {workflow_name}.json is missing or a placeholder")

        node_map = load_node_map(workflow_name)

        prefix = f"meshes/{project_id}/{entity_type}s/{job_id}"
        workflow = inject(workflow, node_map, {
            "image": source_url,
            "seed": seed_val,
            "filename_prefix": prefix,
        })

        prompt_id = await submit(workflow)

        asset.status = "mesh_processing"
        asset.mesh_job_id = job_id
        asset.params = {**(asset.params or {}), "seed": seed_val, "workflow": workflow_name}

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


def _find_meshes_by_prefix(
    project_id: str, entity_type: str, job_id: str, dual: bool = True
) -> tuple[str | None, str | None]:
    """Locate the mesh GLB(s) a mesh workflow exports under the injected prefix.

    Trellis2 (``dual=True``) names both outputs via StringConcatenate:
    ``{base}_Textured_*.glb`` and ``{base}_WhiteMesh_*.glb``. Single-output
    workflows (``dual=False``, e.g. TripoSplat's SaveGLB) write one file
    directly at ``{base}_*.glb``. Returns each as a path relative to
    COMFY_OUTPUT_DIR. ``*_web.glb`` (optimizer output) is always excluded so
    it can never be mistaken for the source mesh.
    """
    base = os.path.join(COMFY_OUTPUT_DIR, f"meshes/{project_id}/{entity_type}s/{job_id}")

    def _first(pattern: str) -> str | None:
        matches = sorted(m for m in glob.glob(pattern) if not m.endswith("_web.glb"))
        return os.path.relpath(matches[0], COMFY_OUTPUT_DIR) if matches else None

    if dual:
        return _first(f"{base}_Textured*.glb"), _first(f"{base}_WhiteMesh*.glb")
    return _first(f"{base}_*.glb"), None


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
                dual_output = MESH_WORKFLOWS[asset.entity_type]["dual_output"]
                textured_url, white_url = _find_meshes_by_prefix(
                    asset.project_id, asset.entity_type, asset.mesh_job_id, dual=dual_output
                )
                if textured_url:
                    # ComfyUI can report "completed" even when the graph was
                    # rejected at validation (e.g. an out-of-range node input)
                    # and produced no output — only declare ready once an
                    # actual textured mesh file is confirmed on disk.
                    asset.mesh_url = textured_url
                    if white_url:
                        asset.white_mesh_url = white_url
                    asset.status = "mesh_ready"
                    job.status = "completed"
                else:
                    asset.status = "mesh_failed"
                    asset.error = "ComfyUI finished but produced no mesh file (workflow may have failed validation)"
                    job.status = "failed"
                    job.error = "No output file found"
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

    workflow_name = MESH_WORKFLOWS[asset.entity_type]["workflow"]

    ref_result = await db.execute(select(Reference).where(Reference.id == asset.source_reference_id))
    ref = ref_result.scalars().first()
    if not ref:
        raise ValueError("Source reference not found or was deleted")

    if not (ref.processed_url or ref.url):
        raise ValueError("Source reference has no image")
    source_url = await _resolve_source_for_load(ref)

    job_id = str(uuid.uuid4())
    seed_val = random.randint(1, MAX_MESH_SEED)

    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=workflow_name,
        query=f"mesh/{asset.entity_type}/{asset.entity_id}/retry",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset.id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(workflow_name)
        if workflow.get("_placeholder"):
            raise RuntimeError(f"Mesh workflow not yet configured — {workflow_name}.json is missing or a placeholder")

        node_map = load_node_map(workflow_name)

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
        asset.params = {**(asset.params or {}), "seed": seed_val, "workflow": workflow_name}
        asset.mesh_url = None
        asset.white_mesh_url = None
        asset.web_mesh_url = None
        asset.web_status = None

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


async def get_mesh_file(
    asset3d_id: str, db: AsyncSession, rigged: bool = False, raw: bool = False, white: bool = False
) -> bytes | None:
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        return None

    if white:
        url = asset.white_mesh_url  # untextured base mesh (for re-texturing)
    elif rigged:
        url = asset.rigged_mesh_url
    elif not raw and asset.web_status == "ready" and asset.web_mesh_url:
        url = asset.web_mesh_url  # transparently serve the optimized proxy
    else:
        url = asset.mesh_url
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

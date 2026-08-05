import glob
import os
import shutil
import uuid
import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset3D, JobRecord, Reference, Project
from services.comfyui_client import load_workflow, load_node_map, inject
from services.job_handlers import register, frontend_status
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

    seed_val = params.get("seed", random.randint(1, MAX_MESH_SEED)) if params else random.randint(1, MAX_MESH_SEED)
    dual_output = MESH_WORKFLOWS[entity_type]["dual_output"]

    asset = Asset3D(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        source_reference_id=ref.id,
        status="queued",
        params={**(params or {}), "seed": seed_val, "workflow": workflow_name},
    )
    db.add(asset)
    await db.flush()
    asset_id = asset.id

    # Enqueue only — the worker submits, polls and finalizes via the mesh handler.
    # No job_id in the payload, so each attempt mints a fresh output prefix.
    job = JobRecord(
        kind="mesh",
        status="queued",
        model_name=workflow_name,
        query=f"mesh/{entity_type}/{entity_id}",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset_id,
        payload={
            "workflow_name": workflow_name,
            "entity_type": entity_type,
            "project_id": project_id,
            "source_url": source_url,
            "seed": seed_val,
            "dual_output": dual_output,
            "asset3d_id": asset_id,
        },
    )
    db.add(job)
    await db.commit()

    return asset_id, warning


async def build_mesh(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    workflow_name = payload["workflow_name"]
    entity_type = payload["entity_type"]
    project_id = payload["project_id"]
    job_id = payload.get("job_id") or str(uuid.uuid4())
    seed_val = payload.get("seed") or random.randint(1, MAX_MESH_SEED)

    workflow = load_workflow(workflow_name)
    if workflow.get("_placeholder"):
        raise RuntimeError(
            f"Mesh workflow not yet configured — {workflow_name}.json is missing or a placeholder"
        )
    node_map = load_node_map(workflow_name)

    prefix = f"meshes/{project_id}/{entity_type}s/{job_id}"
    workflow = inject(workflow, node_map, {
        "image": payload["source_url"],
        "seed": seed_val,
        "filename_prefix": prefix,
    })
    meta = {"job_id": job_id, "seed": seed_val, "prefix": prefix}
    return workflow, meta


async def on_complete_mesh(payload: dict, outputs: dict, db: AsyncSession) -> None:
    """Locate the exported GLB(s) and mark the asset mesh_ready.

    A "completed" ComfyUI run that produced no file means the graph was rejected
    at validation — raise so the worker records the failure (and retries).
    """
    asset = await db.get(Asset3D, payload["asset3d_id"])
    if asset is None:
        return
    textured_url, white_url = _find_meshes_by_prefix(
        payload["project_id"], payload["entity_type"], payload["job_id"],
        dual=payload.get("dual_output", True),
    )
    if not textured_url:
        raise RuntimeError(
            "ComfyUI finished but produced no mesh file (workflow may have failed validation)"
        )
    asset.mesh_url = textured_url
    if white_url:
        asset.white_mesh_url = white_url
    asset.mesh_job_id = payload["job_id"]
    asset.status = "mesh_ready"
    await db.commit()


register("mesh", build_mesh, on_complete_mesh)


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
    """Reflect the mesh job's state onto the Asset3D row. Does NOT drive
    progress — the worker submits/polls/finalizes — but keeps the status
    vocabulary (queued / mesh_processing / mesh_ready / mesh_failed) intact so
    the frontend is unchanged."""
    result = await db.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
    asset = result.scalars().first()
    if not asset:
        return None

    # Terminal / non-mesh-processing states are authoritative already.
    if asset.status in ("mesh_ready", "mesh_failed", "rigged", "rig_failed"):
        return asset

    job = (
        await db.execute(
            select(JobRecord)
            .where(JobRecord.entity_type == "asset3d", JobRecord.entity_id == asset3d_id)
            .order_by(JobRecord.created_at.desc())
        )
    ).scalars().first()
    if job is None:
        return asset

    if job.status in ("failed", "cancelled"):
        if asset.status != "mesh_failed":
            asset.status = "mesh_failed"
            asset.error = job.error or "Mesh generation failed"
            await db.commit()
    elif job.status == "running":
        if asset.status != "mesh_processing":
            asset.status = "mesh_processing"
            await db.commit()
    # job.status == "completed" -> on_complete_mesh already set mesh_ready;
    # job.status == "queued"    -> asset stays "queued".

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

    seed_val = random.randint(1, MAX_MESH_SEED)
    dual_output = MESH_WORKFLOWS[asset.entity_type]["dual_output"]

    # Reset the row and enqueue a fresh mesh job; the worker takes it from here.
    asset.status = "queued"
    asset.error = None
    asset.mesh_job_id = None
    asset.params = {**(asset.params or {}), "seed": seed_val, "workflow": workflow_name}
    asset.mesh_url = None
    asset.white_mesh_url = None
    asset.web_mesh_url = None
    asset.web_status = None

    job = JobRecord(
        kind="mesh",
        status="queued",
        model_name=workflow_name,
        query=f"mesh/{asset.entity_type}/{asset.entity_id}/retry",
        seed=seed_val,
        job_type="mesh",
        entity_type="asset3d",
        entity_id=asset.id,
        payload={
            "workflow_name": workflow_name,
            "entity_type": asset.entity_type,
            "project_id": asset.project_id,
            "source_url": source_url,
            "seed": seed_val,
            "dual_output": dual_output,
            "asset3d_id": asset.id,
        },
    )
    db.add(job)
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

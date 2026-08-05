"""Job handler registry (Phase 0, KAN-19).

Each generation *kind* is described by a :class:`JobHandler` pairing two pure-ish
steps that the background worker (KAN-20) drives:

* ``build_workflow(payload, db) -> (workflow_dict, meta)`` — load the workflow
  JSON + its ``.map.json``, inject the payload's inputs, and return the graph
  ready to POST to ComfyUI together with a ``meta`` dict of computed values the
  caller needs afterwards (``job_id``, ``seed``, ``prefix``, ``image_url``).
* ``on_complete(payload, outputs, db) -> None`` — finalize the owning DB row
  once ComfyUI reports the job done.

Keeping workflow construction here (rather than inline in each service) lets the
worker run a job without a browser, and lets a retry rebuild a fresh output
prefix (KAN-21). The existing service functions delegate to these handlers, so
behaviour is unchanged until the endpoints are switched to enqueue in KAN-23.
"""
import os
import uuid
import random
import shutil
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, GeneratedImage, Reference
from services.comfyui_client import load_workflow, load_node_map, inject

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

TXT2IMG_WORKFLOW = "image_z_image_turbo"
IMG2IMG_WORKFLOW = "image_flux2_klein_image_edit_4b_base"
SCENE_WORKFLOW = "image_z_image_turbo"

# Map internal job status to the status strings the frontend already expects on
# the owning row (queued/processing/completed/failed). Keeps the polling flow
# unchanged now that the worker — not the poll endpoint — drives progress.
_JOB_TO_ROW_STATUS = {
    "queued": "queued",
    "running": "processing",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
}


def frontend_status(job_status: str) -> str:
    return _JOB_TO_ROW_STATUS.get(job_status, job_status)

SEED_MAX = 1000000000000000


def _new_seed() -> int:
    return random.randint(1, SEED_MAX)


def _job_id(payload: dict) -> str:
    """Reuse a caller-supplied job_id, else mint one.

    The worker deliberately omits ``job_id`` so every retry attempt gets a fresh
    one — and therefore a fresh output prefix (KAN-21). The legacy service
    callers pass their own so the owning row and the prefix stay in sync.
    """
    return payload.get("job_id") or str(uuid.uuid4())


def _seed(payload: dict) -> int:
    return payload.get("seed") or _new_seed()


# ── source-image resolution (shared by img2img) ─────────────────────────────

async def _resolve_source_image(
    db: AsyncSession,
    source_reference_id: str | None,
    source_asset_image_id: str | None,
    job_id: str,
) -> str | None:
    """Resolve an img2img source down to a filename ComfyUI can LoadImage.

    A reference already living in the input dir is used in place; anything in the
    output dir (a prior generation) is copied into the input dir under a
    per-job name first.
    """
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


# ── build_workflow implementations ──────────────────────────────────────────

async def build_asset_txt2img(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    project_id = payload["project_id"]
    entity_type = payload["entity_type"]
    prompt = payload["prompt"]
    width = payload.get("width")
    height = payload.get("height")

    job_id = _job_id(payload)
    seed_val = _seed(payload)
    prefix = f"assets/{project_id}/{entity_type}s/{job_id}"

    workflow = load_workflow(TXT2IMG_WORKFLOW)
    node_map = load_node_map(TXT2IMG_WORKFLOW)

    overrides = {"prompt": prompt, "seed": seed_val, "filename_prefix": prefix}
    if width is not None:
        overrides["width"] = width
    if height is not None:
        overrides["height"] = height

    workflow = inject(workflow, node_map, overrides)
    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": prefix,
        "image_url": f"{prefix}_00001_.png",
    }
    return workflow, meta


async def build_asset_img2img(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    project_id = payload["project_id"]
    entity_type = payload["entity_type"]
    prompt = payload["prompt"]

    job_id = _job_id(payload)
    seed_val = _seed(payload)
    prefix = f"assets/{project_id}/{entity_type}s/{job_id}"

    source_filename = await _resolve_source_image(
        db,
        payload.get("source_reference_id"),
        payload.get("source_asset_image_id"),
        job_id,
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
    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": prefix,
        "source_filename": source_filename,
        "image_url": f"{prefix}_00001_.png",
    }
    return workflow, meta


async def build_scene_image(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    prompt = payload["prompt"]
    job_id = _job_id(payload)
    seed_val = _seed(payload)

    workflow = load_workflow(SCENE_WORKFLOW)
    node_map = load_node_map(SCENE_WORKFLOW)
    overrides = {
        "prompt": prompt,
        "seed": seed_val,
        "filename_prefix": job_id,
    }
    # Separate negative prompt (KAN-34) — inject() no-ops on workflows whose map
    # has no negative_node, so this is safe for every graph.
    if payload.get("negative_prompt"):
        overrides["negative_prompt"] = payload["negative_prompt"]
    workflow = inject(workflow, node_map, overrides)
    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": job_id,
        "image_url": f"{job_id}_00001_.png",
    }
    return workflow, meta


# ── on_complete implementations ─────────────────────────────────────────────

async def _finalize_row(model, owner_id: str, payload: dict, db: AsyncSession) -> None:
    if not owner_id:
        return
    row = (
        await db.execute(select(model).where(model.id == owner_id))
    ).scalars().first()
    if not row:
        return
    row.status = "completed"
    if payload.get("image_url"):
        row.image_url = payload["image_url"]
    await db.commit()


async def on_complete_asset_image(payload: dict, outputs: dict, db: AsyncSession) -> None:
    await _finalize_row(AssetImage, payload.get("asset_image_id"), payload, db)


async def on_complete_scene_image(payload: dict, outputs: dict, db: AsyncSession) -> None:
    await _finalize_row(GeneratedImage, payload.get("generation_id"), payload, db)


# ── registry ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobHandler:
    kind: str
    build_workflow: Callable[[dict, AsyncSession], Awaitable[tuple[dict, dict]]]
    on_complete: Callable[[dict, dict, AsyncSession], Awaitable[None]]


HANDLERS: dict[str, JobHandler] = {}


def register(kind, build_workflow, on_complete) -> None:
    """Register a handler for a job kind.

    The image kinds register here; the video / controlled_image / mesh kinds
    register from their own service modules on import (avoiding an import cycle,
    since those services build on this module). main.py imports every router —
    and therefore every service — so the registry is complete at app startup.
    """
    HANDLERS[kind] = JobHandler(kind, build_workflow, on_complete)


register("asset_txt2img", build_asset_txt2img, on_complete_asset_image)
register("asset_img2img", build_asset_img2img, on_complete_asset_image)
register("scene_image", build_scene_image, on_complete_scene_image)

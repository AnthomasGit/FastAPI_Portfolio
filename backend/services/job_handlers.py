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

import logging

from database import (
    AssetImage, GeneratedImage, Reference, Character, scene_characters,
)
from services.comfyui_client import load_workflow, load_node_map, inject
from services.image_workflows import resolve_workflow_name, aspect_ratio_label

logger = logging.getLogger("job_handlers")

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")

TXT2IMG_WORKFLOW = "image_z_image_turbo"
IMG2IMG_WORKFLOW = "image_flux2_klein_image_edit_4b_base"
SCENE_WORKFLOW = "image_z_image_turbo"
# Identity-capable scene workflow: LTX-2.3 MSR (Licon-MSR) composes character
# canonical images as reference subjects into a single still (KAN-36). Used only
# when the scene has canonical identity images; otherwise the plain
# SCENE_WORKFLOW is used.
SCENE_REF_WORKFLOW = "image_msr_ref"
# MSR-style ref maps expose a fixed set of subject slots (image_node,
# image2_node…) rather than an autogrow image_slots list.
_REF_SLOT_KEYS = ["image_node", "image2_node", "image3_node", "image4_node",
                  "image5_node", "image6_node", "image7_node", "image8_node", "image9_node"]
COLOR_MATCH_WORKFLOW = "image_color_match"

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

    # The chosen txt2img model selects the graph; unknown/missing -> default.
    workflow_name = resolve_workflow_name(payload.get("workflow"))
    workflow = load_workflow(workflow_name)
    node_map = load_node_map(workflow_name)

    # Pass both explicit size (Z-Image) and a derived aspect ratio (Krea2's
    # ResolutionSelector); inject() drops whichever this graph's map lacks.
    overrides = {"prompt": prompt, "seed": seed_val, "filename_prefix": prefix}
    if width is not None:
        overrides["width"] = width
    if height is not None:
        overrides["height"] = height
    aspect = aspect_ratio_label(width, height)
    if aspect is not None:
        overrides["aspect_ratio"] = aspect

    workflow = inject(workflow, node_map, overrides)
    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": prefix,
        "workflow": workflow_name,
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


async def resolve_scene_identity_refs(scene_id: str, db: AsyncSession,
                                      max_slots: int) -> list[str]:
    """Stage the canonical identity images of a scene's linked characters as
    COMFY_INPUT_DIR-relative filenames, in a deterministic order (KAN-36).

    A character without a canonical image is skipped (not an error). If more
    characters have canonical images than the workflow has slots, the extras are
    dropped with a warning. Reuses the OUTPUT→INPUT staging pattern from
    asset_image_service._resolve_source_image.
    """
    chars = (await db.execute(
        select(Character).join(scene_characters)
        .where(scene_characters.c.scene_id == scene_id)
        .order_by(Character.name)
    )).scalars().all()

    staged: list[str] = []
    dropped: list[str] = []
    for char in chars:
        if not char.canonical_asset_image_id:
            continue
        asset = await db.get(AssetImage, char.canonical_asset_image_id)
        if not asset or not asset.image_url:
            continue
        if len(staged) >= max_slots:
            dropped.append(char.name)
            continue
        # Canonical images live in COMFY_OUTPUT_DIR under a subfolder; LoadImage
        # only reads COMFY_INPUT_DIR, so stage a flat copy in first.
        input_filename = f"{char.id}_canon.png"
        try:
            shutil.copy2(
                os.path.join(COMFY_OUTPUT_DIR, asset.image_url),
                os.path.join(COMFY_INPUT_DIR, input_filename),
            )
        except OSError:
            logger.warning("identity ref for %s missing on disk (%s) — skipped",
                           char.name, asset.image_url)
            continue
        staged.append(input_filename)

    if dropped:
        logger.warning("scene %s has more identity refs than the workflow's %d slots; "
                       "dropped: %s", scene_id, max_slots, ", ".join(dropped))
    return staged


async def build_scene_image(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    prompt = payload["prompt"]
    job_id = _job_id(payload)
    seed_val = _seed(payload)

    # Feed character identity references when requested and available; fall back
    # to the plain workflow when the scene has no canonical images (KAN-36).
    ref_files: list[str] = []
    scene_id = payload.get("scene_id")
    ref_slot_keys: list[str] = []
    if scene_id and payload.get("identity_refs"):
        ref_map = load_node_map(SCENE_REF_WORKFLOW)
        ref_slot_keys = [k for k in _REF_SLOT_KEYS if k in ref_map]
        ref_files = await resolve_scene_identity_refs(scene_id, db, max_slots=len(ref_slot_keys))

    if ref_files:
        workflow_name = SCENE_REF_WORKFLOW
        workflow = load_workflow(workflow_name)
        node_map = load_node_map(workflow_name)
        # LiconMSR requires every subject slot to point at a real file, so pad
        # the unused slots by repeating the last reference rather than pruning.
        filled = ref_files + [ref_files[-1]] * (len(ref_slot_keys) - len(ref_files))
        overrides = {"seed": seed_val, "filename_prefix": job_id}
        for idx, filename in enumerate(filled):
            overrides["image" if idx == 0 else f"image{idx + 1}"] = filename
        # MSR drives its prompt through PromptRelayEncode (global/local); also
        # set the plain key so single-prompt graphs work — inject() ignores keys
        # a workflow's map doesn't expose.
        overrides["prompt"] = prompt
        overrides["global_prompt"] = prompt
        overrides["local_prompts"] = prompt
    else:
        workflow_name = SCENE_WORKFLOW
        workflow = load_workflow(workflow_name)
        node_map = load_node_map(workflow_name)
        overrides = {"prompt": prompt, "seed": seed_val, "filename_prefix": job_id}

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
        "workflow": workflow_name,
        "ref_count": len(ref_files),
    }
    return workflow, meta


def _stage_output_to_input(output_rel: str, dest_name: str) -> str:
    """Copy a COMFY_OUTPUT_DIR-relative file into COMFY_INPUT_DIR under a flat
    name so a LoadImage node can read it. Returns the input-relative filename."""
    shutil.copy2(
        os.path.join(COMFY_OUTPUT_DIR, output_rel),
        os.path.join(COMFY_INPUT_DIR, dest_name),
    )
    return dest_name


async def build_character_sheet(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    """One cell of a character sheet (KAN-38): img2img off the character's
    canonical reference when it has one, else txt2img. Prompt and seed come from
    the batch expansion; only the per-cell suffix (already baked into the prompt)
    differs between cells."""
    project_id = payload["project_id"]
    entity_type = payload["entity_type"]
    prompt = payload["prompt"]

    job_id = _job_id(payload)
    seed_val = _seed(payload)
    prefix = f"assets/{project_id}/{entity_type}s/{job_id}"

    source_filename = await _resolve_source_image(
        db, None, payload.get("source_asset_image_id"), job_id,
    )
    if source_filename:
        workflow = load_workflow(IMG2IMG_WORKFLOW)
        node_map = load_node_map(IMG2IMG_WORKFLOW)
        workflow = inject(workflow, node_map, {
            "prompt": prompt, "seed": seed_val,
            "image": source_filename, "filename_prefix": prefix,
        })
    else:
        workflow_name = resolve_workflow_name(payload.get("workflow"))
        workflow = load_workflow(workflow_name)
        node_map = load_node_map(workflow_name)
        workflow = inject(workflow, node_map, {
            "prompt": prompt, "seed": seed_val, "filename_prefix": prefix,
        })
    meta = {"job_id": job_id, "seed": seed_val, "prefix": prefix,
            "image_url": f"{prefix}_00001_.png"}
    return workflow, meta


async def build_color_match(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    """Match a generated still's colours to an approved key frame (KAN-37).

    ``source`` (resolved from the parent job via {"$from_parent": "image_url"})
    and ``reference_image`` are both COMFY_OUTPUT_DIR-relative; stage both into
    the input dir before injecting.
    """
    job_id = _job_id(payload)
    source_rel = payload["source"]
    reference_rel = payload["reference_image"]

    source_in = _stage_output_to_input(source_rel, f"{job_id}_src.png")
    reference_in = _stage_output_to_input(reference_rel, f"{job_id}_ref.png")

    workflow = load_workflow(COLOR_MATCH_WORKFLOW)
    node_map = load_node_map(COLOR_MATCH_WORKFLOW)

    # Optional film-grain pass: when off, drop the grain node and tap the
    # ColorMatch output directly (KAN-37).
    grain_node = node_map.get("grain_node")
    color_node = node_map.get("color_node")
    output_node = node_map.get("output_node")
    if not payload.get("film_grain") and grain_node and grain_node in workflow:
        workflow.pop(grain_node, None)
        if output_node and color_node:
            workflow[output_node]["inputs"]["images"] = [color_node, 0]
    elif payload.get("film_grain") and grain_node in workflow and payload.get("film_grain_power") is not None:
        workflow[grain_node]["inputs"]["grain_power"] = payload["film_grain_power"]

    workflow = inject(workflow, node_map, {
        "image": source_in,
        "reference_image": reference_in,
        "filename_prefix": job_id,
    })
    meta = {"job_id": job_id, "prefix": job_id, "image_url": f"{job_id}_00001_.png"}
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


@dataclass(frozen=True)
class LocalHandler:
    """A job kind the worker runs in-process, with no ComfyUI round-trip (e.g.
    the PIL contact-sheet composite, KAN-39). ``run(payload, db) -> meta``
    performs the work and finalizes its own owning row; ``meta`` may carry an
    ``image_url`` the worker records on the JobRecord."""
    kind: str
    run: Callable[[dict, AsyncSession], Awaitable[dict]]


HANDLERS: dict[str, JobHandler] = {}
LOCAL_HANDLERS: dict[str, LocalHandler] = {}


def register_local(kind, run) -> None:
    LOCAL_HANDLERS[kind] = LocalHandler(kind, run)


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
# Sheet cells finalize like any asset image; the composite is a local job.
register("character_sheet", build_character_sheet, on_complete_asset_image)
# Colour-match result is a GeneratedImage row, finalized like a scene image.
register("color_match", build_color_match, on_complete_scene_image)

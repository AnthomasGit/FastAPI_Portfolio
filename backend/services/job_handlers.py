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
    AssetImage, GeneratedImage, Reference, Character, Location, Prop,
    scene_characters, scene_locations, scene_props,
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
# Plate expansion / outpaint pass (KAN-43): widen a location plate by per-side
# pixel amounts. Extend-only subset of the Qwen-Image-Edit multi-angle pipeline.
PLATE_OUTPAINT_WORKFLOW = "image_plate_outpaint"
_EXPAND_KEYS = ("expand_left", "expand_right", "expand_top", "expand_bottom")
# Multi-angle 360 (KAN-16 follow-on): fixed base graph; angle branches are
# appended per-request so count/prompts/double-ref are dynamic.
PLATE_ANGLES_WORKFLOW = "image_plate_angles_base"

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


# ── entity primary-image staging (shared by scene stills and shot clips) ────
#
# "Primary image" differs per entity type: a Location's is its establishing
# plate (falling back to its hero canonical), everything else is its canonical.
# Centralised here because three callers need it — scene identity refs, the
# scene background plate, and the per-shot H3 reference slots.

def primary_asset_image_id(entity, entity_type: str) -> str | None:
    """The AssetImage id to feed into generation for this entity, or None."""
    if entity_type == "location":
        return entity.plate_asset_image_id or entity.canonical_asset_image_id
    return getattr(entity, "canonical_asset_image_id", None)


def _staged_name(entity, entity_type: str) -> str:
    # Location plates and character canonicals keep their historical names —
    # existing tests assert on them.
    suffix = "plate" if entity_type == "location" else "canon"
    return f"{entity.id}_{suffix}.png"


async def stage_entity_primary_image(entity, entity_type: str, db: AsyncSession) -> str | None:
    """Stage an entity's primary image into COMFY_INPUT_DIR, returning the flat
    input-relative filename, or None when there is nothing usable.

    Generated images live in COMFY_OUTPUT_DIR under a subfolder but LoadImage
    only reads COMFY_INPUT_DIR, so a flat copy is made first. Missing rows and
    missing files are *skipped with a warning*, never raised: one absent
    reference should degrade a render, not fail a whole overnight batch.
    """
    asset_id = primary_asset_image_id(entity, entity_type)
    if not asset_id:
        return None
    asset = await db.get(AssetImage, asset_id)
    if not asset or not asset.image_url:
        return None
    dest = _staged_name(entity, entity_type)
    try:
        return _stage_output_to_input(asset.image_url, dest)
    except OSError:
        logger.warning("%s %s: primary image missing on disk (%s) — skipped",
                       entity_type, getattr(entity, "name", entity.id), asset.image_url)
        return None


async def resolve_scene_entities(scene_id: str, db: AsyncSession) -> list[tuple[str, object]]:
    """A scene's linked entities as (entity_type, entity), deterministically
    ordered: characters by name, then locations, then props.

    Identity first is deliberate — when there are more entities than reference
    slots, the tail is dropped, and losing a character's likeness is far more
    visible than losing a prop.
    """
    out: list[tuple[str, object]] = []
    for model, join, etype in (
        (Character, scene_characters, "character"),
        (Location, scene_locations, "location"),
        (Prop, scene_props, "prop"),
    ):
        rows = (await db.execute(
            select(model).join(join)
            .where(join.c.scene_id == scene_id)
            .order_by(model.name)
        )).scalars().all()
        out += [(etype, r) for r in rows]
    return out


_ENTITY_MODELS = {"character": Character, "location": Location, "prop": Prop}


async def select_shot_entities(shot, scene_entities: list[tuple[str, object]],
                               db: AsyncSession) -> list[tuple[str, object]]:
    """Apply a shot's `clip_refs` override to its scene's entity list.

    `clip_refs` is null when the shot has no opinion → use the scene default.
    An explicit `[]` means "no references" and is honoured as such. Entries name
    an entity by (entity_type, entity_id) and are returned IN THE GIVEN ORDER,
    because that order becomes the graph's slot order and the prompt's
    <Subject N> numbering.

    Entries whose entity no longer exists are skipped with a warning — the
    column has no FK, so a deleted character leaves dangling ids behind and a
    stale pin must not fail the render.
    """
    refs = shot.clip_refs
    if refs is None:
        return scene_entities
    by_key = {(etype, e.id): (etype, e) for etype, e in scene_entities}

    out: list[tuple[str, object]] = []
    for ref in refs:
        etype, eid = ref.get("entity_type"), ref.get("entity_id")
        hit = by_key.get((etype, eid))
        if hit is None:
            # Pinned entity may be valid but no longer linked to the scene, so
            # fall back to a direct load before giving up.
            model = _ENTITY_MODELS.get(etype)
            entity = await db.get(model, eid) if model and eid else None
            if entity is None:
                logger.warning("shot %s pins unknown %s %s — skipped", shot.id, etype, eid)
                continue
            hit = (etype, entity)
        out.append(hit)
    return out


async def resolve_scene_identity_refs(scene_id: str, db: AsyncSession,
                                      max_slots: int) -> list[str]:
    """Stage the canonical identity images of a scene's linked characters as
    COMFY_INPUT_DIR-relative filenames, in a deterministic order (KAN-36).

    A character without a canonical image is skipped (not an error). If more
    characters have canonical images than the workflow has slots, the extras are
    dropped with a warning.
    """
    chars = (await db.execute(
        select(Character).join(scene_characters)
        .where(scene_characters.c.scene_id == scene_id)
        .order_by(Character.name)
    )).scalars().all()

    staged: list[str] = []
    dropped: list[str] = []
    for char in chars:
        # Characters use the canonical image only — never a plate.
        if not char.canonical_asset_image_id:
            continue
        if len(staged) >= max_slots:
            dropped.append(char.name)
            continue
        filename = await stage_entity_primary_image(char, "character", db)
        if filename is None:
            continue
        staged.append(filename)

    if dropped:
        logger.warning("scene %s has more identity refs than the workflow's %d slots; "
                       "dropped: %s", scene_id, max_slots, ", ".join(dropped))
    return staged


async def resolve_scene_plate(scene_id: str, db: AsyncSession) -> str | None:
    """Stage the establishing plate of a scene's linked Location as a
    COMFY_INPUT_DIR-relative filename, or None (KAN-42).

    A scene with several locations uses the first by name (deterministic) that
    has a plate, logging the choice. Locations without a plate are skipped; a
    missing file on disk is treated as no plate rather than an error.
    """
    locs = (await db.execute(
        select(Location).join(scene_locations)
        .where(scene_locations.c.scene_id == scene_id)
        .order_by(Location.name)
    )).scalars().all()
    # Strictly the plate here, never the canonical fallback: this is the scene's
    # *background*, and a hero location shot would be the wrong image entirely.
    plated = [l for l in locs if l.plate_asset_image_id]
    if not plated:
        return None
    loc = plated[0]
    if len(plated) > 1:
        logger.info("scene %s has %d plated locations; using '%s'",
                    scene_id, len(plated), loc.name)
    return await stage_entity_primary_image(loc, "location", db)


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

    # Location background plate (KAN-42): feed the scene's location plate as the
    # fixed establishing background when the chosen workflow exposes a background
    # node. inject() no-ops on graphs without one, so this is safe everywhere; a
    # batch can opt out via use_plate=False.
    plate_file = None
    if scene_id and payload.get("use_plate", True) and "background_node" in node_map:
        plate_file = await resolve_scene_plate(scene_id, db)
        if plate_file:
            overrides["background_image"] = plate_file

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
        "plate": bool(plate_file),
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


async def build_plate_expand(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    """Widen a source plate by per-side pixel amounts (KAN-43).

    The source (``source_asset_image_id``, an existing plate AssetImage) is
    staged OUTPUT→INPUT, then fed through the outpaint graph with the requested
    ``expand_*`` amounts. Result is a new, wider plate image.
    """
    project_id = payload["project_id"]
    job_id = _job_id(payload)
    seed_val = _seed(payload)
    prefix = f"assets/{project_id}/locations/{job_id}"

    source_filename = await _resolve_source_image(
        db, None, payload.get("source_asset_image_id"), job_id,
    )
    if not source_filename:
        raise ValueError("No source plate provided for plate_expand")

    workflow = load_workflow(PLATE_OUTPAINT_WORKFLOW)
    node_map = load_node_map(PLATE_OUTPAINT_WORKFLOW)

    overrides = {"image": source_filename, "seed": seed_val, "filename_prefix": prefix}
    for key in _EXPAND_KEYS:
        if payload.get(key) is not None:
            overrides[key] = int(payload[key])
    if payload.get("prompt"):
        overrides["prompt"] = payload["prompt"]
    if payload.get("steps") is not None:
        overrides["steps"] = int(payload["steps"])

    workflow = inject(workflow, node_map, overrides)
    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": prefix,
        "source_filename": source_filename,
        "image_url": f"{prefix}_00001_.png",
    }
    return workflow, meta


def _safe_slot(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "angle"))


def _append_angle_branch(workflow: dict, nid: int, *, prompt: str, prefix: str,
                         double_ref: bool, seed: int, steps: int, node_map: dict) -> int:
    """Append one camera-angle branch (8 nodes) to the graph, wired to the shared
    CLIP/VAE/LoRA-model/expanded-plate-latent. Returns the next free node id.

    Mirrors a branch of full_pipeline_360.json: text → multi-ref method → two
    chained ReferenceLatents → zero-out negative → KSampler → decode → save. The
    double-ref toggle points the sampler's positive at ref #2 (on) or ref #1
    (off) — on keeps the source strongly; off gives the angle model more freedom.
    """
    clip = node_map["clip_node"]
    vae = node_map["vae_node"]
    model = node_map["angles_model_node"]
    latent = node_map["shared_ref_latent_node"]

    t, m, r1, r2, z, k, v, s = (str(nid + i) for i in range(8))
    workflow[t] = {"inputs": {"text": prompt, "clip": [clip, 0]}, "class_type": "CLIPTextEncode"}
    workflow[m] = {"inputs": {"conditioning": [t, 0], "reference_latents_method": "index_timestep_zero"},
                   "class_type": "FluxKontextMultiReferenceLatentMethod"}
    workflow[r1] = {"inputs": {"conditioning": [m, 0], "latent": [latent, 0]}, "class_type": "ReferenceLatent"}
    workflow[r2] = {"inputs": {"conditioning": [r1, 0], "latent": [latent, 0]}, "class_type": "ReferenceLatent"}
    workflow[z] = {"inputs": {"conditioning": [r1, 0]}, "class_type": "ConditioningZeroOut"}
    positive = r2 if double_ref else r1
    workflow[k] = {"inputs": {"seed": seed, "steps": steps, "cfg": 2.5, "sampler_name": "euler",
                              "scheduler": "simple", "denoise": 1, "model": [model, 0],
                              "positive": [positive, 0], "negative": [z, 0], "latent_image": [latent, 0]},
                   "class_type": "KSampler"}
    workflow[v] = {"inputs": {"samples": [k, 0], "vae": [vae, 0]}, "class_type": "VAEDecode"}
    workflow[s] = {"inputs": {"filename_prefix": prefix, "images": [v, 0]}, "class_type": "SaveImage"}
    return nid + 8


async def build_plate_angles(payload: dict, db: AsyncSession) -> tuple[dict, dict]:
    """Multi-angle 360 fan-out (KAN-16 follow-on): from one source plate, extend
    it (front / 0deg) and render N camera angles off the same widened
    environment, as a single ComfyUI graph producing one image per angle.

    Angle count/prompts are dynamic (branches appended here); ``double_ref`` and
    ``steps`` apply to every sampler; one shared ``seed`` keeps the environment
    consistent across angles. Returns meta.angle_results = [{asset_image_id,
    image_url, slot}] so on_complete can finalize each output.
    """
    project_id = payload["project_id"]
    angles = payload["angles"]                # [{slot, prompt, asset_image_id}]
    double_ref = payload.get("double_ref", True)
    steps = int(payload.get("steps") or 20)

    job_id = _job_id(payload)
    seed_val = _seed(payload)
    base_prefix = f"assets/{project_id}/locations/{job_id}"

    source_filename = await _resolve_source_image(
        db, None, payload.get("source_asset_image_id"), job_id,
    )
    if not source_filename:
        raise ValueError("No source plate provided for plate_angles")

    workflow = load_workflow(PLATE_ANGLES_WORKFLOW)
    node_map = load_node_map(PLATE_ANGLES_WORKFLOW)

    overrides = {"image": source_filename}
    for key in _EXPAND_KEYS:
        if payload.get(key) is not None:
            overrides[key] = int(payload[key])
    workflow = inject(workflow, node_map, overrides)

    # Extend sampler: shared seed/steps, and honour the double-ref toggle.
    extend_k = workflow[node_map["extend_sampler_node"]]["inputs"]
    extend_k["seed"] = seed_val
    extend_k["steps"] = steps
    if not double_ref:
        extend_k["positive"] = [node_map["extend_single_ref_node"], 0]

    # Allocate branch ids above the base graph's max BEFORE optionally removing
    # the front node — otherwise the pop lowers the max and a branch reuses id 60.
    nid = max(int(k) for k in workflow) + 1

    # Front (0deg) = the extended plate itself (node 13 → its SaveImage). Optional:
    # a single-angle *regenerate* omits it (front_asset_image_id=None) so it does
    # not spawn a throwaway front image. Node 18 still consumes node 13, so the
    # extend stage runs regardless.
    results = []
    front_id = payload.get("front_asset_image_id")
    front_node = node_map["front_output_node"]
    if front_id:
        front_prefix = f"{base_prefix}_front"
        workflow[front_node]["inputs"]["filename_prefix"] = front_prefix
        results.append({"asset_image_id": front_id,
                        "image_url": f"{front_prefix}_00001_.png", "slot": "front"})
    else:
        workflow.pop(front_node, None)
    for angle in angles:
        slot = _safe_slot(angle.get("slot"))
        prefix = f"{base_prefix}_{slot}"
        nid = _append_angle_branch(
            workflow, nid, prompt=angle.get("prompt") or "", prefix=prefix,
            double_ref=double_ref, seed=seed_val, steps=steps, node_map=node_map,
        )
        results.append({"asset_image_id": angle.get("asset_image_id"),
                        "image_url": f"{prefix}_00001_.png", "slot": slot})

    meta = {
        "job_id": job_id,
        "seed": seed_val,
        "prefix": base_prefix,
        # Queue-UI representative: the front if present, else the first angle.
        "image_url": results[0]["image_url"] if results else None,
        "angle_results": results,
    }
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


async def on_complete_plate_angles(payload: dict, outputs: dict, db: AsyncSession) -> None:
    """Finalize every angle output of a plate_angles job — one AssetImage per
    branch, each at its predicted per-branch filename (KAN-16 follow-on)."""
    for r in payload.get("angle_results") or []:
        await _finalize_row(AssetImage, r.get("asset_image_id"), {"image_url": r.get("image_url")}, db)


async def on_complete_location_plate(payload: dict, outputs: dict, db: AsyncSession) -> None:
    """Finalize the plate's AssetImage, then point the Location at it (KAN-41).
    The plate becomes the location's current establishing background."""
    await _finalize_row(AssetImage, payload.get("asset_image_id"), payload, db)
    location_id = payload.get("location_id")
    if not location_id:
        return
    loc = await db.get(Location, location_id)
    if loc is not None:
        loc.plate_asset_image_id = payload.get("asset_image_id")
        await db.commit()


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
# Location plate: a wide txt2img whose completion also sets Location.plate (KAN-41).
register("location_plate", build_asset_txt2img, on_complete_location_plate)
# Plate expansion / outpaint: result is a new AssetImage linked to the source (KAN-43).
register("plate_expand", build_plate_expand, on_complete_asset_image)
# Multi-angle 360: one job, many AssetImages (front + N angles).
register("plate_angles", build_plate_angles, on_complete_plate_angles)
# Colour-match result is a GeneratedImage row, finalized like a scene image.
register("color_match", build_color_match, on_complete_scene_image)

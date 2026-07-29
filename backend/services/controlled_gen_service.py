"""Beauty pass: turn a staged capture into a cinematic, identity-corrected still.

The R3F stage gives us correct composition/geometry but the render carries
3D-proxy artifacts — plastic materials, and faces distorted by the generated
mesh. This runs the capture's **color** pass through Flux Klein 9B img2img
(consistency LoRA + the bfs_head face LoRA), with the shot's character
reference photo fed in as a second ReferenceLatent to restore identity.

Conditioning on the textured color pass rather than the depth map is the
project's standing decision (the staged render already encodes the geometry,
so depth-ControlNet is redundant here — and no ControlNet/IP-Adapter model is
installed on this box anyway). The output becomes the first frame for video.
"""

import uuid
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    SceneCapture, SceneStaging, GeneratedImage, Scene, JobRecord, Asset3D, Reference,
)
from services.comfyui_client import load_workflow, load_node_map, inject, submit
from services.comfyui_service import construct_prompt

WORKFLOW_NAME = "image_klein_beauty"


async def get_capture(capture_id: str, db: AsyncSession) -> SceneCapture | None:
    result = await db.execute(
        select(SceneCapture).where(SceneCapture.id == capture_id)
    )
    return result.scalars().first()


async def has_inflight_generation(capture_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(GeneratedImage).where(
            GeneratedImage.capture_id == capture_id,
            GeneratedImage.status.in_(["queued", "processing"]),
        )
    )
    return result.scalars().first() is not None


async def _resolve_identity_reference(capture: SceneCapture, db: AsyncSession) -> str | None:
    """Find a character reference photo for whoever is actually staged in this shot.

    Walks the capture's frozen staging snapshot rather than the scene's links,
    so a close-up that only placed one character feeds only that character —
    not the whole cast. Returns a COMFY_INPUT_DIR-relative filename.
    """
    snapshot = capture.staging_snapshot or {}
    placements = snapshot.get("placements") or []
    asset_ids = [p.get("asset3d_id") for p in placements if p.get("asset3d_id")]
    if not asset_ids:
        return None

    result = await db.execute(
        select(Asset3D).where(
            Asset3D.id.in_(asset_ids), Asset3D.entity_type == "character"
        )
    )
    assets = result.scalars().all()
    if not assets:
        return None

    # v1 conditions on a single identity; multi-subject reference is the
    # documented next step (see the video roadmap in 3d-staging-lld-sdlc.md).
    for asset in assets:
        refs = await db.execute(
            select(Reference)
            .where(
                Reference.entity_type == "character",
                Reference.entity_id == asset.entity_id,
            )
            .order_by(Reference.sort_order)
        )
        for ref in refs.scalars().all():
            filename = ref.processed_url or ref.url
            if filename and "/" not in filename:
                # Must live flat in COMFY_INPUT_DIR for LoadImage to read it.
                return filename
    return None


async def generate_controlled_image(
    capture: SceneCapture,
    db: AsyncSession,
    prompt_override: str | None = None,
    params: dict | None = None,
) -> str:
    staging = await db.get(SceneStaging, capture.staging_id)
    if not staging:
        raise ValueError(f"Staging not found for capture: {capture.id}")

    scene = await db.get(Scene, staging.scene_id)
    if not scene:
        raise ValueError(f"Scene not found for capture: {capture.id}")

    prompt_text = prompt_override or await construct_prompt(scene.id, db)

    params = params or {}
    seed_val = params.get("seed") or random.randint(1, 1000000000000000)

    # The beauty pass edits the textured render, not the depth map.
    source_image = capture.color_map_url or capture.depth_map_url

    # Fall back to the source image itself when no character reference exists
    # (a prop-only shot, or a character with no photo). A LoadImage pointing at
    # a missing file fails ComfyUI's whole-graph validation silently, so this
    # slot must always resolve to a real file.
    ref_image = await _resolve_identity_reference(capture, db) or source_image

    gen = GeneratedImage(
        scene_id=scene.id,
        project_id=scene.project_id,
        capture_id=capture.id,
        kind="beauty",
        prompt=prompt_text,
        status="queued",
        params={"seed": seed_val, "workflow": WORKFLOW_NAME, "ref_image": ref_image},
    )
    db.add(gen)
    await db.flush()
    gen_id = gen.id

    job_id = str(uuid.uuid4())
    job = JobRecord(
        job_id=job_id,
        status="queued",
        model_name=WORKFLOW_NAME,
        query=prompt_text,
        seed=seed_val,
        job_type="controlled_image",
        entity_type="generated_image",
        entity_id=gen_id,
    )
    db.add(job)
    await db.flush()

    try:
        workflow = load_workflow(WORKFLOW_NAME)
        node_map = load_node_map(WORKFLOW_NAME)

        workflow = inject(workflow, node_map, {
            "prompt": prompt_text,
            "seed": seed_val,
            "filename_prefix": job_id,
            "image": source_image,
            "ref_image": ref_image,
        })

        prompt_id = await submit(workflow)

        gen.status = "processing"
        gen.job_id = job_id
        gen.prompt_id = prompt_id
        gen.image_url = f"{job_id}_00001_.png"
        job.status = "processing"
        job.prompt_id = prompt_id
        job.image_url = gen.image_url
        await db.commit()

    except Exception as e:
        gen.status = "failed"
        gen.error = str(e)
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.utcnow()
        await db.commit()

    return gen_id

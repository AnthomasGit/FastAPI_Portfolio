import uuid
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SceneCapture, SceneStaging, GeneratedImage, Scene, JobRecord
from services.comfyui_client import load_workflow, load_node_map, inject, submit
from services.comfyui_service import construct_prompt

WORKFLOW_NAME = "image_controlnet_ipadapter"
DEFAULT_CONTROLNET_STRENGTH = 0.8


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
    strength = params.get("controlnet_strength", DEFAULT_CONTROLNET_STRENGTH)
    seed_val = params.get("seed") or random.randint(1, 1000000000000000)

    gen = GeneratedImage(
        scene_id=scene.id,
        project_id=scene.project_id,
        capture_id=capture.id,
        kind="controlled",
        prompt=prompt_text,
        status="queued",
        params={"controlnet_strength": strength, "seed": seed_val},
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
            "image": capture.depth_map_url,
            "controlnet_strength": strength,
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

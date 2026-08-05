import os, json, uuid, random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Scene, GeneratedImage, JobRecord, Project, Character, Location, Prop, scene_characters, scene_locations, scene_props
from services.comfyui_client import poll
from services.job_handlers import frontend_status

WORKFLOW_NAME = "image_z_image_turbo"


async def construct_prompt(scene_id: str, db: AsyncSession) -> str:
    scene = await db.get(Scene, scene_id)
    if not scene:
        return ""

    char_rows = await db.execute(
        select(Character).join(scene_characters).where(scene_characters.c.scene_id == scene_id)
    )
    characters = char_rows.scalars().all()

    loc_rows = await db.execute(
        select(Location).join(scene_locations).where(scene_locations.c.scene_id == scene_id)
    )
    locations = loc_rows.scalars().all()

    prop_rows = await db.execute(
        select(Prop).join(scene_props).where(scene_props.c.scene_id == scene_id)
    )
    props_list = prop_rows.scalars().all()

    char_desc = "; ".join([f"{c.name}: {c.description}" for c in characters if c.description])
    loc_desc = "; ".join([f"{l.name}: {l.description}" for l in locations if l.description])
    prop_desc = "; ".join([f"{p.name}: {p.description}" for p in props_list if p.description])

    prompt = f"Scene: {scene.slugline}\n"
    prompt += f"Screenplay: {scene.screenplay}\n"
    if char_desc:
        prompt += f"Characters: {char_desc}\n"
    if loc_desc:
        prompt += f"Location: {loc_desc}\n"
    if prop_desc:
        prompt += f"Props: {prop_desc}\n"
    prompt += "Style: cinematic, film still, professional lighting, high detail, 4K"

    return prompt


async def generate_scene_image(scene_id: str, db: AsyncSession) -> str:
    """Enqueue a scene-image job and return immediately.

    The background worker (KAN-20) claims the JobRecord, submits to ComfyUI,
    and finalizes the GeneratedImage row via the scene_image handler's
    on_complete — so generation survives the request and the browser tab.
    """
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise ValueError(f"Scene not found: {scene_id}")

    prompt_text = await construct_prompt(scene_id, db)

    gen = GeneratedImage(scene_id=scene_id, prompt=prompt_text, status="queued")
    db.add(gen)
    await db.flush()
    gen_id = gen.id

    job = JobRecord(
        kind="scene_image",
        status="queued",
        entity_type="generated_image",
        entity_id=gen_id,
        payload={"prompt": prompt_text, "generation_id": gen_id},
    )
    db.add(job)
    await db.commit()

    return gen_id


async def poll_generation_status(generation_id: str, db: AsyncSession) -> dict:
    """Report status from the row + its job. Does NOT drive progress — the
    worker owns that — but keeps the (id, status, image_url) shape unchanged."""
    gen = (
        await db.execute(select(GeneratedImage).where(GeneratedImage.id == generation_id))
    ).scalars().first()
    if not gen:
        return {"status": "not_found"}

    if gen.status in ("completed", "failed"):
        return {"id": gen.id, "status": gen.status, "image_url": gen.image_url}

    job = (
        await db.execute(
            select(JobRecord)
            .where(JobRecord.entity_type == "generated_image",
                   JobRecord.entity_id == generation_id)
            .order_by(JobRecord.created_at.desc())
        )
    ).scalars().first()

    if job is not None:
        mapped = frontend_status(job.status)
        if mapped == "failed" and gen.status != "failed":
            gen.status = "failed"
            await db.commit()
        return {"id": gen.id, "status": mapped, "image_url": gen.image_url}

    # Legacy inline path (e.g. controlled generation, until KAN-24 migrates it):
    # no JobRecord, so poll ComfyUI directly by prompt_id.
    if gen.prompt_id:
        result = await poll(gen.prompt_id)
        if result["status"] == "error":
            gen.status = "failed"
            await db.commit()
            return {"id": gen.id, "status": "failed", "image_url": gen.image_url}
        elif result["status"] == "completed":
            gen.status = "completed"
            await db.commit()
            return {"id": gen.id, "status": "completed", "image_url": gen.image_url}

    return {"id": gen.id, "status": gen.status, "image_url": gen.image_url}

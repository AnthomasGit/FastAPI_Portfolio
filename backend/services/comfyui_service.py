import os, json, uuid, random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Scene, GeneratedImage, Project, Character, Location, Prop, scene_characters, scene_locations, scene_props
from services.comfyui_client import submit, poll
from services.job_handlers import HANDLERS

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
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise ValueError(f"Scene not found: {scene_id}")

    prompt_text = await construct_prompt(scene_id, db)

    gen = GeneratedImage(
        scene_id=scene_id,
        prompt=prompt_text,
        status="queued"
    )
    db.add(gen)
    await db.flush()
    gen_id = gen.id

    try:
        job_id = str(uuid.uuid4())
        seed_val = random.randint(1, 1000000000000000)

        workflow, meta = await HANDLERS["scene_image"].build_workflow(
            {"prompt": prompt_text, "job_id": job_id, "seed": seed_val},
            db,
        )

        prompt_id = await submit(workflow)

        gen.status = "processing"
        gen.job_id = job_id
        gen.prompt_id = prompt_id
        gen.image_url = meta["image_url"]
        await db.commit()

    except Exception as e:
        gen.status = "failed"
        await db.commit()

    return gen_id


async def poll_generation_status(generation_id: str, db: AsyncSession) -> dict:
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == generation_id))
    gen = result.scalars().first()
    if not gen:
        return {"status": "not_found"}

    if gen.status in ("completed", "failed"):
        return {"id": gen.id, "status": gen.status, "image_url": gen.image_url}

    if gen.prompt_id:
        result = await poll(gen.prompt_id)
        if result["status"] == "error":
            gen.status = "failed"
            await db.commit()
            return {"id": gen.id, "status": "failed"}
        elif result["status"] == "completed":
            gen.status = "completed"
            await db.commit()
            return {"id": gen.id, "status": "completed", "image_url": gen.image_url}

    return {"id": gen.id, "status": gen.status}

import os, json, uuid, random, httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Scene, GeneratedImage, Project, Character, Location, Prop, scene_characters, scene_locations, scene_props

COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://comfyui:8188")

WORKFLOW_FILE = os.environ.get("COMFY_WORKFLOW", "image_z_image_turbo.json")
WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..", "workflows")


def load_workflow() -> dict:
    filepath = os.path.join(WORKFLOW_DIR, WORKFLOW_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Workflow not found: {filepath}")


def inject_prompt(workflow: dict, prompt_text: str, job_id: str, seed: int) -> dict:
    for node_id, node_data in workflow.items():
        inputs = node_data.get("inputs", {})
        class_type = node_data.get("class_type", "")

        if class_type == "CLIPTextEncode" and "text" in inputs:
            if "negative" in node_id or "neg" in str(node_data).lower():
                continue
            inputs["text"] = prompt_text

        if "KSampler" in class_type or "Sampler" in class_type:
            if "seed" in inputs:
                inputs["seed"] = seed

        if "filename_prefix" in inputs:
            inputs["filename_prefix"] = job_id

    return workflow


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
        workflow = load_workflow()
        job_id = str(uuid.uuid4())
        seed_val = random.randint(1, 1000000000000000)
        workflow = inject_prompt(workflow, prompt_text, job_id, seed_val)

        payload = {
            "prompt": workflow,
            "client_id": f"storyboard-{uuid.uuid4()}"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            if response.status_code != 200:
                gen.status = "failed"
                await db.commit()
                return gen_id

            prompt_id = response.json().get("prompt_id")

        gen.status = "processing"
        gen.job_id = job_id
        gen.prompt_id = prompt_id
        gen.image_url = f"{job_id}_00001_.png"
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
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                history_res = await client.get(f"{COMFY_API_URL}/history/{gen.prompt_id}")
                history = history_res.json().get(gen.prompt_id, {})

                if history:
                    if history.get("status", {}).get("status_str") == "error":
                        gen.status = "failed"
                        await db.commit()
                        return {"id": gen.id, "status": "failed"}

                    gen.status = "completed"
                    await db.commit()
                    return {"id": gen.id, "status": "completed", "image_url": gen.image_url}
        except Exception:
            pass

    return {"id": gen.id, "status": gen.status}

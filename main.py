import os
import json
import uuid
import random
import asyncio

import httpx
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# Pull the ComfyUI URL from the environment variable set in docker-compose
COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://127.0.0.1:8188")
COMFY_WS_URL = COMFY_API_URL.replace("http://", "ws://").replace("https://", "wss://")

# This decides what workflow/model to use
class ModelName(str, Enum):
    imagegen = "imagegen"
    # add new workflow

# Maps the Enum->local JSON
WORKFLOW_MAP = {
    ModelName.imagegen: "image_z_image_turbo.json",
    # direct ModelName.new_workflow to JSON
}

# Used for JIT model warming
class WarmupRequest(BaseModel):
    model_name: ModelName

# Pydantic model for strict input validation
class GenerateRequest(BaseModel):
    model_name: ModelName
    query: str
app = FastAPI(title="FastAPI_Portfolio")

# Set for job tracking (in memory)->switch to Redis(multi-pod))
jobs_db = {}

# Dynamically loads the ComfyUI workflow JSON into memory from local directory.
def load_workflow(workflow: ModelName) -> dict:
    # Obtains filename from dictionary
    filename = WORKFLOW_MAP.get(workflow)

    if not filename:
        raise HTTPException(status_code=500, detail="Workflow not found for {workflow.value}")

    # Grabs filepath depending on OS file structure
    filepath = os.path.join("workflows", filename)

    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Workflow not found.")

# For JIT model warming: Parses and modifies JSON to decrease steps and image size. (Loads model in VRAM with minimal output)
def prepare_warmup_workflow(workflow: dict) -> dict:
    """Dynamically finds and shrinks samplers/images for a lightning-fast warmup."""
    for node_id, node_data in workflow.items():
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        # 1. Drop steps to 1 to bypass long compute times
        if "KSampler" in class_type and "steps" in inputs:
            inputs["steps"] = 1

        # 2. Shrink the latent image so the GPU doesn't waste VRAM generating a dummy image
        elif "LatentImage" in class_type and "width" in inputs:
            inputs["width"] = 256
            inputs["height"] = 256

        # 3. Inject a dummy prompt
        elif class_type == "CLIPTextEncode" and "text" in inputs:
            inputs["text"] = "warmup"

    return workflow

# 
@app.post("/portfolio/warmup")
async def trigger_warmup(request: WarmupRequest):
    """Fires a 1-step dummy payload to load models into VRAM."""
    # 1. Load the specific workflow they clicked
    base_workflow = load_workflow(request.model_name)

    # 2. Modify it for a fast warmup
    warmup_workflow = prepare_warmup_workflow(base_workflow)

    payload = {
        "prompt": warmup_workflow,
        "client_id": f"warmup-{uuid.uuid4()}"
    }

    # 3. Fire and forget! Do not 'await' the full execution.
    asyncio.create_task(send_warmup_to_comfy(payload))

    # Immediately let the frontend continue loading the next page
    return {"status": "warming_up", "model": request.model_name.value}


async def send_warmup_to_comfy(payload: dict):
    """Background task to push the payload to ComfyUI."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            print("🚀 Warmup payload sent to ComfyUI successfully.")
        except Exception as e:
            print(f"⚠️ Warmup request failed (server might be down): {e}")

@app.post("/portfolio/imagegen")
async def queue_generation(request: GenerateRequest):
    # Load JSON according to model_name
    workflow = load_workflow(request.model_name)

    # Inject user input into JSON text_encoder node
    try:
        workflow["57:27"]["inputs"]["text"] = request.query
    except KeyError:
        print("Warning: Node ID '57:27' for text prompt not found. Check your JSON!")
    # Inject random seed to ensure unique generation
    try:
        workflow["57:3"]["inputs"]["seed"] = random.randint(1, 1000000000000000)
    except KeyError:
        print("Warning: Node ID '57:3' for text seed not found. Check your JSON!")

    # Create unique client-side ID, replace with login
    client_id = str(uuid.uuid4())
    # loads payload with JSON containing (user prompt and node to file information) and unique id
    payload = {"prompt": workflow, "client_id": client_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try: # Sends JSON payload to headless comfy. Submits through "/prompt" endpoint
            response = await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"ComfyUI rejected the workflow: {response.text}")
            response.raise_for_status()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="ComfyUI server is unreachable")
    # "/prompt" returns prompt ID
    prompt_id = response.json().get("prompt_id")

    # Unique id for DB.
    job_id = str(uuid.uuid4())

    # Save to DB
    # Key: job_id        Value: prompt_id
    jobs_db[job_id] = {"prompt_id": prompt_id, "status": "queued"}

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Image generation started"
    }

@app.get("/portfolio/status/{job_id}")
    # The frontend polls this endpoint to check if the image is ready.
async def check_status(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")

    # Retrieve prompt_id
    prompt_id = jobs_db[job_id]["prompt_id"]

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Query "/history{prompt_id}"
        history_rest = await client.get(f"{COMFY_API_URL}/history/{prompt_id}")
        in_history = history_rest.json().get(prompt_id, {})

        # If the prompt_id query returns from "/history" then imagegen is complete, retrieve.
        if in_history:
            #init image info store
            img_info = None
            outputs = in_history.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    # Grab the entire dictionary ComfyUI provides (filename, subfolder, type)
                    img_info = node_output["images"][0]
                    break

            # Once img_info is filled, return URL where frontend can download image
            if img_info:
               jobs_db[job_id]["status"] = "completed"
               # Store the exact parameters safely in our backend memory
               jobs_db[job_id]["image_info"] = img_info

               return {
                   "job_id": job_id,
                   "status": "completed",
                   "download_url": f"/portfolio/image/{job_id}"
               }
            else:
                return {"job_id": job_id, "status": "failed", "detail": "No image output found."}
        # If it's not in the history yet, it's still queued or executing
        return {"job_id": job_id, "status": "processing"}

@app.get("/portfolio/image/{job_id}")
async def get_image(job_id: str):
    """Serves the generated image securely with job_id."""
    #retrieve image_info
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")

    img_info = jobs_db[job_id]["image_info"]

    params = {"filename": img_info["filename"]}

    # Only add subfolder and type if ComfyUI actually provided them as non-empty strings
    if img_info.get("subfolder"):
        params["subfolder"] = img_info["subfolder"]
    if img_info.get("type"):
        params["type"] = img_info["type"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Pass all the exact parameters back to ComfyUI so it never gets confused
        img_res = await client.get(
            f"{COMFY_API_URL}/view",
               params=params
        )
        if img_res.status_code != 200:
            raise HTTPException(status_code=404, detail="Image not found on server.")

        return Response(content=img_res.content, media_type="image/png")

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
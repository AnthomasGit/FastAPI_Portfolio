import os
import json
import uuid
import random
import asyncio
from dataclasses import Field

import httpx
import websockets
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
            #init filename store
            filename = None
            outputs = in_history.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    filename = node_output["images"][0]["filename"]
                    break

            # Once filename is filled, return URL where frontend can download image
            if filename:
               jobs_db[job_id]["status"] = "completed"
               return {
                   "job_id": job_id,
                   "status": "completed",
                   "download_url": f"/portfolio/image/{filename}"
               }
            else:
                return {"job_id": job_id, "status": "failed", "detail": "No image output found."}
        # If it's not in the history yet, it's still queued or executing
        return {"job_id": job_id, "status": "processing"}

@app.get(f"/portfolio/image/{filename}")
async def get_image(filename: str):
    """Serves the generated image."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        img_res = await client.get(f"{COMFY_API_URL}/view/", params={"filename": filename})
        if img_res.status_code != 200:
            raise HTTPException(status_code=404, detail="Image not found on server.")

        return Response(content=img_res.content, media_type="image/png")

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
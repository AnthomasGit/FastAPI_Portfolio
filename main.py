import os
import json
import uuid
import asyncio
import httpx
import websockets
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

# Pull the ComfyUI URL from the environment variable set in docker-compose
COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://127.0.0.1:8188")
COMFY_WS_URL = COMFY_API_URL.replace("http://", "ws://").replace("https://", "wss://")


class ModelName(str, Enum):
    imagegen = "imagegen"


app = FastAPI(title="FastAPI_Portfolio")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.get("/portfolio/{model_name}/{query}")
async def generate_pic(model_name: ModelName, query: str):
    if model_name != ModelName.imagegen:
        raise HTTPException(status_code=400, detail="Invalid model")

    # 1. Load your exported ComfyUI "API Format" JSON
    # (In production, load this from a saved .json file)
    workflow = load_default_workflow()

    # 2. Inject the user's query dynamically
    # NOTE: "6" is typically the CLIPTextEncode node ID for the positive prompt, 
    # but you must verify this ID against your specific workflow JSON.
    try:
        workflow["57:27"]["inputs"]["text"] = query
    except KeyError:
        pass  # Handle missing node gracefully in production

    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 3. Queue the prompt in ComfyUI
        try:
            response = await client.post(f"{COMFY_API_URL}/prompt", json=payload)
            response.raise_for_status()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="ComfyUI server is unreachable")

        prompt_id = response.json().get("prompt_id")

        # 4. Wait for the generation to finish via WebSocket
        await wait_for_comfy_execution(client_id, prompt_id)

        # 5. Fetch the execution history to find the generated filename
        history_res = await client.get(f"{COMFY_API_URL}/history/{prompt_id}")
        history = history_res.json().get(prompt_id, {})

        filename = None
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                filename = node_output["images"][0]["filename"]
                break

        if not filename:
            raise HTTPException(status_code=500, detail="Generation failed or no image output.")

        # 6. Fetch the actual image bytes and return them
        img_res = await client.get(f"{COMFY_API_URL}/view", params={"filename": filename})
        return Response(content=img_res.content, media_type="image/png")


async def wait_for_comfy_execution(client_id: str, prompt_id: str):
    """Listens to the ComfyUI WebSocket until the specific prompt_id finishes."""
    async with websockets.connect(f"{COMFY_WS_URL}/ws?clientId={client_id}") as websocket:
        while True:
            out = await websocket.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message.get("type") == "executing":
                    data = message.get("data")
                    # If node is None and it matches our prompt, execution is done
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        break


def load_default_workflow():
    """Helper function to return your raw API workflow dict."""
    # Replace this with a json.load() of your actual workflow file
    return {
        "3": {"class_type": "KSampler", "inputs": {"seed": 123}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}
    }
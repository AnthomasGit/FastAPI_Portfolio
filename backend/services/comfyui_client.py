import os
import json
import uuid
import httpx

COMFY_API_URL = os.environ.get("COMFY_API_URL", "http://comfyui:8188")
WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..", "workflows")


def load_workflow(name: str) -> dict:
    filepath = os.path.join(WORKFLOW_DIR, f"{name}.json")
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Workflow not found: {filepath}")


def load_node_map(name: str) -> dict:
    filepath = os.path.join(WORKFLOW_DIR, f"{name}.map.json")
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Node map not found: {filepath}")


INJECTION_MAP = {
    "prompt": "prompt_node",
    "seed": "seed_node",
    "filename_prefix": "output_node",
    "image": "image_node",
}


def inject(workflow: dict, node_map: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        node_key = INJECTION_MAP.get(key)
        if node_key is None:
            continue
        node_id = node_map.get(node_key)
        if node_id is None:
            continue
        node = workflow.get(node_id)
        if node is None:
            continue
        inputs = node.get("inputs", {})

        if key == "prompt":
            if "text" in inputs:
                inputs["text"] = value

        elif key == "seed":
            if "seed" in inputs:
                inputs["seed"] = value
            elif "noise_seed" in inputs:
                inputs["noise_seed"] = value

        elif key == "filename_prefix":
            if "filename_prefix" in inputs:
                inputs["filename_prefix"] = value

        elif key == "image":
            if "image" in inputs:
                inputs["image"] = value

    return workflow


async def submit(workflow: dict) -> str:
    payload = {
        "prompt": workflow,
        "client_id": f"storyboard-{uuid.uuid4()}",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{COMFY_API_URL}/prompt", json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"ComfyUI submit failed (HTTP {response.status_code}): {response.text}"
            )
        data = response.json()
        return data["prompt_id"]


async def poll(prompt_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{COMFY_API_URL}/history/{prompt_id}")
            history = response.json().get(prompt_id, {})
            if not history:
                return {"status": "not_found", "outputs": None}

            status_str = history.get("status", {}).get("status_str", "completed")
            if status_str == "error":
                return {"status": "error", "outputs": history.get("outputs", {})}

            return {"status": "completed", "outputs": history.get("outputs", {})}
    except (httpx.TimeoutException, httpx.RequestError):
        return {"status": "not_found", "outputs": None}


async def view_file(filename: str, subfolder: str | None = None) -> bytes:
    params = {"filename": filename}
    if subfolder:
        params["subfolder"] = subfolder
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{COMFY_API_URL}/view", params=params)
        if response.status_code != 200:
            raise RuntimeError(
                f"ComfyUI view failed (HTTP {response.status_code}): {response.text}"
            )
        return response.content

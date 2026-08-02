import os
import json
import logging
import uuid
import httpx

logger = logging.getLogger(__name__)

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


# override key -> (node-map key, candidate input fields in priority order).
#
# Data-driven rather than a per-key if/elif chain: a workflow that exposes a
# new knob only needs a map entry, not Python changes. The candidate tuple
# exists because the same logical input lands on differently-named fields
# depending on the node class — a seed is "seed" on KSampler but "noise_seed"
# on RandomNoise; a filename prefix is "filename_prefix" on Save* nodes but
# "value" on a PrimitiveString feeding StringConcatenate; the INTConstant /
# FloatConstant primitives the LTX graphs use for width/height/fps all carry
# a plain "value". First candidate present on the node wins.
INJECTION_MAP = {
    "prompt": ("prompt_node", ("text",)),
    "negative_prompt": ("negative_node", ("text",)),
    "seed": ("seed_node", ("seed", "noise_seed")),
    "filename_prefix": ("output_node", ("filename_prefix", "value")),
    "image": ("image_node", ("image",)),
    # A second LoadImage slot, for workflows that take an identity/style
    # reference alongside the main image (e.g. the Klein beauty pass feeds a
    # character's reference photo in to restore a face the 3D proxy distorted).
    "ref_image": ("ref_image_node", ("image",)),
    # Subject slots 2-4 + background plate for multi-subject reference video
    # (LTX-2.3 MSR composes these into its conditioning guide).
    "image2": ("image2_node", ("image",)),
    "image3": ("image3_node", ("image",)),
    "image4": ("image4_node", ("image",)),
    "background_image": ("background_node", ("image",)),
    # PromptRelayEncode carries two prompts on ONE node: a global block that
    # describes each reference image's identity, and the per-beat local script.
    # Both map keys therefore point at the same node id but write differently.
    "global_prompt": ("global_prompt_node", ("global_prompt",)),
    "local_prompts": ("local_prompts_node", ("local_prompts",)),
    "width": ("width_node", ("value", "width")),
    "height": ("height_node", ("value", "height")),
    "fps": ("fps_node", ("value", "frame_rate")),
    "duration": ("duration_node", ("value",)),
    # LiconMSR's OWN frame_count: how many frames its reference/identity guide
    # spans. Unrelated to "duration" above (the output clip's length) — do not
    # conflate the two, they drive completely different parts of the graph.
    "reference_frame_count": ("reference_frame_count_node", ("frame_count", "value")),
    "controlnet_strength": ("controlnet_node", ("strength",)),
    # Driving-video pose transfer (SCAIL-2): a VHS_LoadVideo source plus the
    # frame count the sampler generates.
    "driving_video": ("video_node", ("video",)),
    "length": ("length_node", ("length", "value")),
}


def inject(workflow: dict, node_map: dict, overrides: dict) -> dict:
    """Write ``overrides`` into ``workflow`` at the node ids named by ``node_map``.

    Silently skips overrides a workflow does not expose — every workflow maps
    only the knobs it has, and callers pass a superset. Unroutable keys are
    logged rather than raised: a graph that quietly ignored an input still
    produces a *plausible but wrong* video, and that is far cheaper to notice
    here than at poll time, where ComfyUI reports success either way.
    """
    for key, value in overrides.items():
        entry = INJECTION_MAP.get(key)
        if entry is None:
            logger.warning("inject: unknown override key %r (ignored)", key)
            continue
        node_key, fields = entry

        node_id = node_map.get(node_key)
        if node_id is None:
            logger.warning(
                "inject: override %r supplied but this workflow's map has no %r",
                key, node_key,
            )
            continue

        node = workflow.get(node_id)
        if node is None:
            logger.warning(
                "inject: map key %r points at node %r, absent from the workflow",
                node_key, node_id,
            )
            continue

        inputs = node.get("inputs", {})
        for field in fields:
            if field in inputs:
                inputs[field] = value
                break
        else:
            logger.warning(
                "inject: node %r (for %r) has none of the expected inputs %s",
                node_id, key, fields,
            )

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

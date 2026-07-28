"""Background removal service for Storyboard Pro.

Runs birefnet (the same model ComfyUI's LoadBackgroundRemovalModel /
RemoveBackground nodes use) locally on CPU, without going through ComfyUI's
job queue — this is meant to be a fast, synchronous-feeling call from the
backend, not a submit-and-poll workflow. Shares the same
COMFY_INPUT_DIR/COMFY_OUTPUT_DIR volumes as the API and ComfyUI so it can
read reference images and write the cleaned result back where the API
already expects staged input images.

CPU-only by design: no GPU is reserved for this service (or the main API
container) in docker-compose — only the `comfyui` service has one.
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import inference

COMFY_INPUT_DIR = os.environ.get("COMFY_INPUT_DIR", "/opt/ComfyUI/input")
COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
_ALLOWED_ROOTS = [os.path.normpath(COMFY_INPUT_DIR), os.path.normpath(COMFY_OUTPUT_DIR)]

app = FastAPI(title="Storyboard Pro background remover")


class RemoveBackgroundRequest(BaseModel):
    input_path: str
    output_path: str


def _validate_path(path: str) -> str:
    """Reject any path that doesn't fall under COMFY_INPUT_DIR/COMFY_OUTPUT_DIR."""
    norm = os.path.normpath(path)
    for root in _ALLOWED_ROOTS:
        if norm == root or norm.startswith(root + os.sep):
            return norm
    raise HTTPException(status_code=400, detail=f"path outside allowed dirs: {path}")


@app.on_event("startup")
async def _load_model_at_startup():
    # Load once at boot rather than on the first request, so request latency
    # is consistent and the (largeish) weights aren't re-read from disk per call.
    inference.get_model()


@app.get("/health")
async def health():
    try:
        inference.get_model()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"model not loaded: {e}")
    return {"status": "ok", "weights": os.environ.get("BIREFNET_WEIGHTS", "(default)")}


@app.post("/remove-background")
async def remove_background(req: RemoveBackgroundRequest):
    input_path = _validate_path(req.input_path)
    output_path = _validate_path(req.output_path)
    if not os.path.isfile(input_path):
        raise HTTPException(status_code=404, detail=f"input image not found: {req.input_path}")

    try:
        stats = inference.remove_background(input_path, output_path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"background removal failed: {e}")

    return {"status": "ok", "output_path": output_path, **stats}

"""Mesh optimizer service for Storyboard Pro.

A tiny FastAPI wrapper that runs `bake_optimize.py` inside headless Blender.
It shares the `/opt/ComfyUI/output` volume with ComfyUI and the API, so it
reads the generated GLB and writes the optimized `*_web.glb` right back where
the API's mesh proxy already resolves paths (relative to COMFY_OUTPUT_DIR).

Blender bake is CPU-only, so this service needs no GPU and runs in parallel
with ComfyUI's GPU work.
"""

import asyncio
import json
import os
import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
BLENDER_BIN = os.environ.get("BLENDER_BIN", "/opt/blender/blender")
SCRIPT = os.environ.get("BAKE_SCRIPT", "/app/bake_optimize.py")
TIMEOUT_SECONDS = int(os.environ.get("OPTIMIZE_TIMEOUT", "600"))

app = FastAPI(title="Storyboard Pro mesh optimizer")


class OptimizeRequest(BaseModel):
    input_rel: str
    output_rel: str
    target_tris: int = 20000
    normal_size: int = 1024
    texture_size: int = 2048
    reuv: bool = False


def _safe_join(base: str, rel: str) -> str:
    """Join and reject any path that escapes COMFY_OUTPUT_DIR."""
    base_n = os.path.normpath(base)
    path = os.path.normpath(os.path.join(base_n, rel))
    if path != base_n and not path.startswith(base_n + os.sep):
        raise HTTPException(status_code=400, detail=f"path escapes output dir: {rel}")
    return path


@app.get("/health")
async def health():
    try:
        proc = await asyncio.create_subprocess_exec(
            BLENDER_BIN, "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        version = out.decode(errors="ignore").splitlines()[0] if out else "unknown"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"blender not runnable: {e}")
    return {"status": "ok", "blender": version, "output_dir": COMFY_OUTPUT_DIR}


@app.post("/optimize")
async def optimize(req: OptimizeRequest):
    abs_in = _safe_join(COMFY_OUTPUT_DIR, req.input_rel)
    abs_out = _safe_join(COMFY_OUTPUT_DIR, req.output_rel)
    if not os.path.isfile(abs_in):
        raise HTTPException(status_code=404, detail=f"input GLB not found: {req.input_rel}")
    os.makedirs(os.path.dirname(abs_out) or ".", exist_ok=True)

    cmd = [
        BLENDER_BIN, "-b", "--python", SCRIPT, "--",
        "--input", abs_in, "--output", abs_out,
        "--target-tris", str(req.target_tris),
        "--normal-size", str(req.normal_size),
        "--texture-size", str(req.texture_size),
    ]
    if req.reuv:
        cmd.append("--reuv")

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="optimization timed out")

    stdout = out.decode(errors="ignore")
    stderr = err.decode(errors="ignore")
    if proc.returncode != 0:
        raise HTTPException(status_code=500,
                            detail=f"bake failed (exit {proc.returncode}): {stderr[-1500:]}")

    m = re.search(r"RESULT_JSON:(\{.*\})", stdout)
    if not m:
        raise HTTPException(status_code=500,
                            detail=f"no RESULT_JSON in output: {stderr[-800:]}")
    return {"status": "ok", "output_rel": req.output_rel, **json.loads(m.group(1))}

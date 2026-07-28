"""Background removal via birefnet — the same model ComfyUI's
LoadBackgroundRemovalModel/RemoveBackground nodes use, run locally on CPU
instead of through ComfyUI's job queue (see bg_remover/ for the standalone
model code). Two modes, mirroring services/mesh_optimize_service.py:
- **compose**: POST to the dedicated ``bg-remover`` service (``BG_REMOVER_URL``).
- **native dev**: no bg-remover container, so run bg_remover/inference.py
  directly as a subprocess (needs a Python with torch/torchvision/safetensors
  on it — set BG_REMOVER_PYTHON if that isn't the default ``python3``).
"""

import asyncio
import json
import os
import re
import uuid

import httpx

BG_REMOVER_URL = os.environ.get("BG_REMOVER_URL")  # e.g. http://bg-remover:8400 (compose)
BG_REMOVER_PYTHON = os.environ.get("BG_REMOVER_PYTHON", "python3")
BG_REMOVER_SCRIPT = os.environ.get(
    "BG_REMOVER_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "bg_remover", "inference.py"),
)
REMOVE_BACKGROUND_TIMEOUT = float(os.environ.get("REMOVE_BACKGROUND_TIMEOUT", "60"))


async def _run_via_http(input_path: str, output_path: str) -> dict:
    async with httpx.AsyncClient(timeout=REMOVE_BACKGROUND_TIMEOUT) as client:
        resp = await client.post(
            f"{BG_REMOVER_URL}/remove-background",
            json={"input_path": input_path, "output_path": output_path},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"bg-remover HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


async def _run_via_subprocess(input_path: str, output_path: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        BG_REMOVER_PYTHON, os.path.abspath(BG_REMOVER_SCRIPT),
        "--input", input_path, "--output", output_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=REMOVE_BACKGROUND_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"bg-remover subprocess failed: {err.decode(errors='ignore')[-800:]}")
    m = re.search(r"RESULT_JSON:(\{.*\})", out.decode(errors="ignore"))
    return json.loads(m.group(1)) if m else {}


async def remove_background(input_path: str, output_dir: str) -> str:
    output_filename = f"{uuid.uuid4()}.png"
    output_path = os.path.join(output_dir, output_filename)

    if BG_REMOVER_URL:
        await _run_via_http(input_path, output_path)
    else:
        await _run_via_subprocess(input_path, output_path)

    return output_filename

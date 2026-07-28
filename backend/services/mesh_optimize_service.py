"""Web-mesh optimization: bake a lightweight GLB from a generated mesh.

Runs after an Asset3D reaches ``mesh_ready``. Two modes:
- **compose**: POST to the dedicated ``optimizer`` service (``OPTIMIZER_URL``),
  which runs Blender headless — mirrors how the app already talks to ComfyUI.
- **native dev**: no optimizer container, so run ``bake_optimize.py`` directly
  via a local Blender subprocess (``blender`` + ``gltf-transform`` on PATH).

Failure is non-fatal: ``web_status='failed'`` and the API keeps serving the raw
mesh, so the editor never breaks.
"""

import asyncio
import json
import os
import re

import httpx
from sqlalchemy import select

from database import SessionLocal, Asset3D

COMFY_OUTPUT_DIR = os.environ.get("COMFY_OUTPUT_DIR", "/opt/ComfyUI/output")
OPTIMIZER_URL = os.environ.get("OPTIMIZER_URL")  # e.g. http://optimizer:8300 (compose)
BLENDER_BIN = os.environ.get("BLENDER_BIN", "blender")
BAKE_SCRIPT = os.environ.get(
    "BAKE_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "bake_optimize.py"),
)
TARGET_TRIS = int(os.environ.get("WEB_MESH_TARGET_TRIS", "20000"))
OPTIMIZE_TIMEOUT = float(os.environ.get("OPTIMIZE_TIMEOUT", "600"))


def _web_output_rel(mesh_rel: str) -> str:
    base, _ext = os.path.splitext(mesh_rel)
    return f"{base}_web.glb"


async def _run_via_http(input_rel: str, output_rel: str) -> dict:
    async with httpx.AsyncClient(timeout=OPTIMIZE_TIMEOUT) as client:
        resp = await client.post(
            f"{OPTIMIZER_URL}/optimize",
            json={"input_rel": input_rel, "output_rel": output_rel, "target_tris": TARGET_TRIS},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"optimizer HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


async def _run_via_subprocess(input_rel: str, output_rel: str) -> dict:
    abs_in = os.path.join(COMFY_OUTPUT_DIR, input_rel)
    abs_out = os.path.join(COMFY_OUTPUT_DIR, output_rel)
    os.makedirs(os.path.dirname(abs_out) or ".", exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        BLENDER_BIN, "-b", "--python", os.path.abspath(BAKE_SCRIPT), "--",
        "--input", abs_in, "--output", abs_out, "--target-tris", str(TARGET_TRIS),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=OPTIMIZE_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"bake failed: {err.decode(errors='ignore')[-800:]}")
    m = re.search(r"RESULT_JSON:(\{.*\})", out.decode(errors="ignore"))
    return json.loads(m.group(1)) if m else {}


async def optimize_web_mesh(asset3d_id: str) -> None:
    """Background task: produce the optimized web GLB and record it on the asset."""
    async with SessionLocal() as session:
        result = await session.execute(select(Asset3D).where(Asset3D.id == asset3d_id))
        asset = result.scalars().first()
        if not asset or not asset.mesh_url:
            return
        input_rel = asset.mesh_url
        output_rel = _web_output_rel(input_rel)
        try:
            if OPTIMIZER_URL:
                await _run_via_http(input_rel, output_rel)
            else:
                await _run_via_subprocess(input_rel, output_rel)
            asset.web_mesh_url = output_rel
            asset.web_status = "ready"
        except Exception as e:  # noqa: BLE001 - never let optimization break the asset
            asset.web_status = "failed"
            print(f"[mesh_optimize] {asset3d_id} failed: {e}")
        await session.commit()

"""Workflow registry endpoint (KAN-45).

Serves the derived per-workflow parameter schemas so the frontend can render
generation controls generically (KAN-46) instead of hard-coding a form per
graph.
"""
from fastapi import APIRouter

from services.workflow_registry import list_workflows
from services.chains import list_chains

router = APIRouter()


@router.get("/api/workflows")
async def get_workflows(kind: str | None = None):
    """All registered workflows, optionally filtered by ``kind`` (image|video|3d|post)."""
    return {"workflows": list_workflows(kind)}


@router.get("/api/chains")
async def get_chains():
    """Named job chains with their per-stage availability (KAN-47). A chain with
    ``available: false`` names the workflow/kind still to be exported."""
    return {"chains": list_chains()}

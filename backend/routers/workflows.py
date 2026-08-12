"""Workflow registry endpoint (KAN-45).

Serves the derived per-workflow parameter schemas so the frontend can render
generation controls generically (KAN-46) instead of hard-coding a form per
graph.
"""
from fastapi import APIRouter

from services.workflow_registry import list_workflows

router = APIRouter()


@router.get("/api/workflows")
async def get_workflows(kind: str | None = None):
    """All registered workflows, optionally filtered by ``kind`` (image|video|3d|post)."""
    return {"workflows": list_workflows(kind)}

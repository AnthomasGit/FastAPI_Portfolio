"""Queue-aware polling: a slow-but-healthy render must not false-time-out and
trigger a resubmit storm (the multi-angle 360 runaway)."""
import os
import json

import pytest
import respx
from httpx import Response
from unittest.mock import AsyncMock

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

import services.job_worker as jw
from services.comfyui_client import COMFY_API_URL, queue_contains


# ── queue_contains ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_queue_contains_running_and_pending():
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/queue").mock(return_value=Response(200, json={
            "queue_running": [[0, "pid-run", {}, {}, []]],
            "queue_pending": [[1, "pid-pend", {}, {}, []]],
        }))
        assert await queue_contains("pid-run") is True
        assert await queue_contains("pid-pend") is True
        assert await queue_contains("pid-missing") is False


@pytest.mark.asyncio
async def test_queue_contains_swallows_errors():
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/queue").mock(return_value=Response(500, text="boom"))
        assert await queue_contains("whatever") is False


# ── _poll_until_done ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_does_not_timeout_while_queued(monkeypatch):
    """History is empty for several cycles, but the prompt sits in ComfyUI's
    queue the whole time — must keep waiting (no poll_timeout) and complete."""
    monkeypatch.setattr(jw, "JOB_POLL_INTERVAL", 0.0)
    monkeypatch.setattr(jw, "JOB_POLL_TIMEOUT", 0.02)  # tiny: would trip if counted
    monkeypatch.setattr(jw, "poll", AsyncMock(side_effect=(
        [{"status": "not_found", "outputs": None}] * 5 + [{"status": "completed", "outputs": {}}]
    )))
    monkeypatch.setattr(jw, "queue_contains", AsyncMock(return_value=True))

    result = await jw._poll_until_done("pid")
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_poll_times_out_when_lost(monkeypatch):
    """Absent from BOTH history and queue past the timeout → declared lost."""
    monkeypatch.setattr(jw, "JOB_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(jw, "JOB_POLL_TIMEOUT", 0.02)
    monkeypatch.setattr(jw, "poll", AsyncMock(return_value={"status": "not_found", "outputs": None}))
    monkeypatch.setattr(jw, "queue_contains", AsyncMock(return_value=False))

    result = await jw._poll_until_done("pid")
    assert result["status"] == "error"
    assert result["reason"] == "poll_timeout"


@pytest.mark.asyncio
async def test_poll_surfaces_comfy_error_reason(monkeypatch):
    """A ComfyUI execution_error is passed through as the failure reason."""
    from services.comfyui_client import _extract_error
    history = {"status": {"status_str": "error", "messages": [
        ["execution_start", {}],
        ["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}],
    ]}}
    reason = _extract_error(history)
    assert "KSampler" in reason and "out of memory" in reason

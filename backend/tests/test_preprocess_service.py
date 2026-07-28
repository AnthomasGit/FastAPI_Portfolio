import json
import os
import pytest
import respx
from httpx import Response
from unittest.mock import patch, AsyncMock, MagicMock

from services.preprocess_service import remove_background


# ── HTTP mode (BG_REMOVER_URL set — compose) ────────────────────────────


@pytest.mark.asyncio
@patch("services.preprocess_service.BG_REMOVER_URL", "http://bg-remover:8400")
async def test_remove_background_http_mode(tmp_path):
    with respx.mock:
        route = respx.post("http://bg-remover:8400/remove-background").mock(
            return_value=Response(200, json={"status": "ok", "width": 100, "height": 100})
        )

        filename = await remove_background(str(tmp_path / "in.png"), str(tmp_path))

        assert route.called
        sent = json.loads(route.calls[0].request.content)
        assert sent["input_path"] == str(tmp_path / "in.png")
        assert sent["output_path"] == str(tmp_path / filename)
        assert filename.endswith(".png")


@pytest.mark.asyncio
@patch("services.preprocess_service.BG_REMOVER_URL", "http://bg-remover:8400")
async def test_remove_background_http_error_raises(tmp_path):
    with respx.mock:
        respx.post("http://bg-remover:8400/remove-background").mock(
            return_value=Response(500, text="model not loaded")
        )
        with pytest.raises(RuntimeError, match="bg-remover HTTP 500"):
            await remove_background(str(tmp_path / "in.png"), str(tmp_path))


# ── Subprocess mode (BG_REMOVER_URL unset — native dev fallback) ────────


@pytest.mark.asyncio
@patch("services.preprocess_service.BG_REMOVER_URL", None)
@patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_remove_background_subprocess_mode(mock_exec, tmp_path):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(
        b'RESULT_JSON:{"width": 100, "height": 100, "mask_mean": 30.0}', b"",
    ))
    proc.returncode = 0
    mock_exec.return_value = proc

    filename = await remove_background(str(tmp_path / "in.png"), str(tmp_path))

    assert filename.endswith(".png")
    args = mock_exec.call_args.args
    assert "--input" in args and str(tmp_path / "in.png") in args
    assert "--output" in args


@pytest.mark.asyncio
@patch("services.preprocess_service.BG_REMOVER_URL", None)
@patch("asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_remove_background_subprocess_failure_raises(mock_exec, tmp_path):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b"torch not found"))
    proc.returncode = 1
    mock_exec.return_value = proc

    with pytest.raises(RuntimeError, match="bg-remover subprocess failed"):
        await remove_background(str(tmp_path / "in.png"), str(tmp_path))

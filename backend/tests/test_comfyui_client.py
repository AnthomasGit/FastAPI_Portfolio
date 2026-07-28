import json
import os
import uuid
import pytest
import respx
from httpx import Response

from services.comfyui_client import (
    load_workflow,
    load_node_map,
    inject,
    submit,
    poll,
    view_file,
    COMFY_API_URL,
)

WORKFLOW_DIR = os.path.join(os.path.dirname(__file__), "..", "workflows")


def _list_workflows():
    """Return (name, workflow_path, map_path) for every workflow pair."""
    results = []
    for fname in os.listdir(WORKFLOW_DIR):
        if fname.endswith(".json") and not fname.endswith(".map.json"):
            name = fname[:-5]
            map_path = os.path.join(WORKFLOW_DIR, fname.replace(".json", ".map.json"))
            if os.path.exists(map_path):
                results.append((name, os.path.join(WORKFLOW_DIR, fname), map_path))
    return results


WORKFLOWS = _list_workflows()


# ── Fixture: every committed workflow+map is valid ──────────────────────


@pytest.mark.parametrize("name,wf_path,map_path", WORKFLOWS)
def test_workflow_and_map_are_valid(name, wf_path, map_path):
    with open(wf_path) as f:
        workflow = json.load(f)
    with open(map_path) as f:
        node_map = json.load(f)

    assert isinstance(workflow, dict), f"{name}.json must be a dict"
    assert len(workflow) > 0, f"{name}.json is empty"

    assert isinstance(node_map, dict), f"{name}.map.json must be a dict"
    assert len(node_map) > 0, f"{name}.map.json is empty"

    for map_key, node_id in node_map.items():
        assert map_key.endswith("_node"), f"Map key {map_key!r} should end with '_node'"
        assert node_id in workflow, (
            f"Node {node_id!r} from map key {map_key!r} "
            f"not found in {name}.json (valid nodes: {list(workflow.keys())})"
        )


# ── Injection snapshot tests ────────────────────────────────────────────


@pytest.mark.parametrize("name,wf_path,map_path", WORKFLOWS)
def test_injection_snapshot(name, wf_path, map_path):
    with open(wf_path) as f:
        workflow = json.load(f)
    with open(map_path) as f:
        node_map = json.load(f)

    overrides = {
        "prompt": "TEST_PROMPT",
        "seed": 12345,
        "filename_prefix": "test-job-abc",
    }
    if "image_node" in node_map:
        overrides["image"] = "test_input.png"

    import copy
    original = copy.deepcopy(workflow)
    injected = inject(workflow, node_map, overrides)

    # Verify prompt was injected into the prompt_node
    prompt_node = node_map.get("prompt_node")
    if prompt_node:
        assert injected[prompt_node]["inputs"]["text"] == "TEST_PROMPT"

    # Verify seed was injected
    seed_node = node_map.get("seed_node")
    if seed_node:
        inputs = injected[seed_node]["inputs"]
        assert (
            inputs.get("seed") == 12345 or inputs.get("noise_seed") == 12345
        ), f"Seed not set in node {seed_node}"

    # Verify filename_prefix was injected. The prefix lands in "filename_prefix"
    # for Save* nodes, or in "value" for a PrimitiveString name node that feeds
    # StringConcatenate-built export names (e.g. the Trellis2 mesh workflow).
    output_node = node_map.get("output_node")
    if output_node:
        out_inputs = injected[output_node]["inputs"]
        assert (
            out_inputs.get("filename_prefix") == "test-job-abc"
            or out_inputs.get("value") == "test-job-abc"
        ), f"filename_prefix not set in node {output_node}"

    # Verify image was injected (if applicable)
    image_node = node_map.get("image_node")
    if image_node:
        assert injected[image_node]["inputs"]["image"] == "test_input.png"

    # Verify other nodes were not modified
    for node_id, node_data in original.items():
        if node_id in (prompt_node, seed_node, output_node, image_node):
            continue
        assert injected[node_id] == node_data, f"Node {node_id} was modified but should not be"


# ── Submit tests (respx mocked) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_accepted():
    prompt_id = str(uuid.uuid4())
    with respx.mock:
        route = respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )
        result = await submit({"dummy": "workflow"})
        assert result == prompt_id
        assert route.called


@pytest.mark.asyncio
async def test_submit_http_error():
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(500, text="Internal Server Error")
        )
        with pytest.raises(RuntimeError, match="ComfyUI submit failed"):
            await submit({"dummy": "workflow"})


# ── Poll tests (respx mocked) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_completed():
    prompt_id = str(uuid.uuid4())
    history_response = {
        prompt_id: {
            "status": {"status_str": "completed"},
            "outputs": {"9": {"images": [{"filename": "output.png", "type": "output"}]}},
        }
    }
    with respx.mock:
        route = respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=history_response)
        )
        result = await poll(prompt_id)
        assert result["status"] == "completed"
        assert result["outputs"] is not None
        assert route.called


@pytest.mark.asyncio
async def test_poll_error_in_history():
    prompt_id = str(uuid.uuid4())
    history_response = {
        prompt_id: {
            "status": {"status_str": "error"},
            "outputs": {},
        }
    }
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json=history_response)
        )
        result = await poll(prompt_id)
        assert result["status"] == "error"


@pytest.mark.asyncio
async def test_poll_not_found():
    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={})
        )
        result = await poll(prompt_id)
        assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_poll_never_completes_timeout():
    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            side_effect=[Response(200, json={}), Response(200, json={})]
        )
        result1 = await poll(prompt_id)
        assert result1["status"] == "not_found"
        result2 = await poll(prompt_id)
        assert result2["status"] == "not_found"


# ── view_file test ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_file():
    with respx.mock:
        route = respx.get(f"{COMFY_API_URL}/view", params={"filename": "test.png"}).mock(
            return_value=Response(200, content=b"fake-image-bytes")
        )
        result = await view_file("test.png")
        assert result == b"fake-image-bytes"
        assert route.called


@pytest.mark.asyncio
async def test_view_file_with_subfolder():
    with respx.mock:
        route = respx.get(
            f"{COMFY_API_URL}/view", params={"filename": "test.png", "subfolder": "sub"}
        ).mock(
            return_value=Response(200, content=b"fake-image-bytes")
        )
        result = await view_file("test.png", subfolder="sub")
        assert result == b"fake-image-bytes"
        assert route.called

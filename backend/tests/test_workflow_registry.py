"""KAN-45 — workflow registry + GET /api/workflows + param validation."""
import os
import uuid

import pytest

from services.comfyui_client import INJECTION_MAP, WORKFLOW_DIR
from services.workflow_registry import (
    build_registry,
    list_workflows,
    validate_params,
    NO_MAP_WORKFLOWS,
)


def _map_names():
    return {f[: -len(".map.json")] for f in os.listdir(WORKFLOW_DIR) if f.endswith(".map.json")}


# ── registry derivation ──────────────────────────────────────────────────

def test_every_mapped_workflow_is_in_registry():
    registry = build_registry()
    assert _map_names() == set(registry)


def test_every_declared_param_exists_in_injection_map():
    for name, entry in build_registry().items():
        for p in entry["params"]:
            assert p["key"] in INJECTION_MAP, f"{name} declares unknown knob {p['key']!r}"


def test_registry_reports_kind_and_label():
    reg = build_registry()
    assert reg["image_z_image_turbo"]["kind"] == "image"
    assert reg["video_ltx_i2v"]["kind"] == "video"
    assert reg["image_color_match"]["kind"] == "post"  # override
    assert reg["3d_triposplat_image_to_gaussian_splat"]["kind"] == "3d"
    assert reg["image_z_image_turbo"]["label"]  # non-empty human label


def test_z_image_exposes_expected_knobs():
    params = {p["key"] for p in build_registry()["image_z_image_turbo"]["params"]}
    # map has prompt/seed/width/height/output nodes.
    assert {"prompt", "width", "height"} <= params
    assert "steps" not in params  # not in this graph's map


def test_outpaint_exposes_all_four_expand_sides():
    params = {p["key"] for p in build_registry()["image_plate_outpaint"]["params"]}
    assert {"expand_left", "expand_right", "expand_top", "expand_bottom"} <= params


# ── regression guard: a workflow json without a map is a mistake ──────────

def test_no_workflow_json_is_missing_a_map():
    jsons = {f[: -len(".json")] for f in os.listdir(WORKFLOW_DIR)
             if f.endswith(".json") and not f.endswith(".map.json")}
    missing = jsons - _map_names() - NO_MAP_WORKFLOWS
    assert not missing, f"workflow(s) without a .map.json (add one or list in NO_MAP_WORKFLOWS): {missing}"


# ── param validation helper ──────────────────────────────────────────────

def test_validate_rejects_unknown_knob_on_known_graph():
    # asset_txt2img → image_z_image_turbo, which exposes no "steps" knob.
    assert validate_params("asset_txt2img", "z_image_turbo", {"steps": 5}) == ["steps"]


def test_validate_accepts_exposed_knob():
    assert validate_params("asset_txt2img", "z_image_turbo", {"width": 768}) == []


def test_validate_rejects_nonsense_knob_even_without_known_graph():
    # scene_image has no single static graph → INJECTION_MAP-membership fallback.
    assert validate_params("scene_image", None, {"not_a_real_knob": 1}) == ["not_a_real_knob"]
    assert validate_params("scene_image", None, {"prompt": "hi"}) == []


def test_validate_empty_params_ok():
    assert validate_params("scene_image", None, {}) == []


# ── GET /api/workflows ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_workflows_lists_all(client):
    resp = await client.get("/api/workflows")
    assert resp.status_code == 200
    names = {w["name"] for w in resp.json()["workflows"]}
    assert _map_names() == names


@pytest.mark.asyncio
async def test_get_workflows_kind_filter(client):
    resp = await client.get("/api/workflows", params={"kind": "video"})
    assert resp.status_code == 200
    kinds = {w["kind"] for w in resp.json()["workflows"]}
    assert kinds == {"video"}


# ── merged hand-authored facts (one endpoint, one param shape) ─────────────

def _by_name(name, kind=None):
    return next(w for w in list_workflows(kind) if w["name"] == name)


def test_video_entry_carries_key_label_and_capabilities():
    """A batch spec submits the workflow KEY, not the graph name, so the merged
    entry has to expose it — otherwise the UI can't build a valid spec."""
    w = _by_name("video_minimax_h3_r2v")
    assert w["workflow_key"] == "minimax_h3_r2v"
    assert w["label"] == "MiniMax H3 Reference-to-Video"
    caps = w["capabilities"]
    assert caps["max_refs"] == 9 and caps["max_ref_audios"] == 3
    # autogrow_slots cannot be derived from a node map and is load-bearing.
    assert caps["autogrow_slots"] is True


def test_video_control_params_are_the_validated_settings():
    """Controls must be the knobs _resolve_settings accepts, not every key the
    graph could physically take — otherwise the UI offers params that 422."""
    w = _by_name("video_minimax_h3_r2v")
    control = {p["key"] for p in w["params"] if p["group"] == "control"}
    assert control == {"sampler_name", "scheduler", "steps", "duration",
                       "aspect_ratio", "megapixels"}


def test_video_params_use_the_same_shape_as_image_params():
    """The whole point of the merge: one renderer for both."""
    vid = next(p for p in _by_name("video_minimax_h3_r2v")["params"]
               if p["key"] == "steps")
    img = next(p for p in _by_name("image_z_image_turbo")["params"]
               if p["key"] == "width")
    assert {"key", "type", "label", "group"} <= set(vid)
    assert {"key", "type", "label", "group"} <= set(img)
    assert vid["type"] == "int" and vid["min"] == 4 and vid["max"] == 60
    # enum options survive for the select controls
    sampler = next(p for p in _by_name("video_minimax_h3_r2v")["params"]
                   if p["key"] == "sampler_name")
    assert sampler["type"] == "enum" and "res_multistep" in sampler["options"]


def test_video_input_slots_are_preserved_alongside_settings():
    """Derived input params still document what the graph consumes."""
    w = _by_name("video_minimax_h3_r2v")
    inputs = {p["key"] for p in w["params"] if p["group"] == "input"}
    assert {"image", "image9", "ref_audio"} <= inputs


def test_image_entry_carries_its_picker_key():
    w = _by_name("image_krea2_turbo")
    assert w["workflow_key"] == "krea2_turbo"
    assert w["capabilities"]["supports_size"] is False


def test_graph_without_a_hand_authored_entry_is_unchanged():
    """Most graphs have no picker entry; they must still list cleanly."""
    w = _by_name("image_color_match")
    assert "workflow_key" not in w
    assert w["kind"] == "post"


@pytest.mark.asyncio
async def test_endpoint_serves_the_merged_shape(client):
    resp = await client.get("/api/workflows", params={"kind": "video"})
    r2v = next(w for w in resp.json()["workflows"] if w["workflow_key"] == "minimax_h3_r2v")
    assert r2v["capabilities"]["max_refs"] == 9


# ── batch endpoint rejects unroutable params (422) ───────────────────────

@pytest.mark.asyncio
async def test_batch_create_422_on_unknown_param(client, project):
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "params": {"bogus_knob": 123},
    })
    assert resp.status_code == 422
    assert "bogus_knob" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_batch_create_ok_with_valid_param(client, db_session, project):
    from database import Scene
    db_session.add(Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1,
                         slugline="S1", screenplay="x", sort_order=0))
    await db_session.commit()
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "params": {"prompt": "a wide shot"},
    })
    assert resp.status_code == 201

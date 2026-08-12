"""Workflow registry (Phase 5, KAN-45).

Nothing in the app currently tells the API or UI *which knobs a given workflow
exposes*. The ``workflows/*.json`` + ``*.map.json`` indirection already knows —
a workflow exposes exactly the ``INJECTION_MAP`` keys whose node-map key its
``.map.json`` contains. So the registry is **derived** from the map files rather
than hand-authored: it cannot drift out of sync with the graphs the way a
separate ``registry.json`` would.

For each workflow the registry reports its name, ``kind`` (image|video|3d|post),
a human label, and a parameter schema: for every exposed knob, the metadata in
``PARAM_META`` (type, label, default, range, enum options, group). The frontend
(KAN-46) renders controls from that schema; ``validate_params`` rejects a batch
spec that names a knob the chosen workflow does not expose, so an unroutable
override 422s at request time instead of silently no-op'ing in ``inject()``.
"""
import os
import json
import functools

from services.comfyui_client import INJECTION_MAP, WORKFLOW_DIR

# ``<name>.json`` files that legitimately have no ``.map.json`` and so are not
# map-driven injection workflows. Documented here so the registry (and the
# regression test) can tell "deliberately map-less" from "someone forgot a map":
#   full_pipeline_*  — the Qwen-Image-Edit reference pipelines the plate
#                      outpaint/angles graphs are exported subsets of.
#   *_api            — API-format exports paired with a map-driven sibling graph.
NO_MAP_WORKFLOWS = {
    "full_pipeline_360",
    "full_pipeline_hires",
    "video_minimax_h3_i2v_api",
    "video_minimax_h3_r2v_api",
}

# kind is derived from the filename prefix (image_/video_/3d_); these are the
# exceptions — image_ graphs that are really post-processing passes over an
# existing image rather than fresh generation.
KIND_OVERRIDES = {
    "image_color_match": "post",
    "image_plate_outpaint": "post",
    "image_plate_angles_base": "post",
    "MeshWithTexturing_6steps_example": "3d",
}

# Per-knob UI/validation metadata, keyed by INJECTION_MAP key.
#   group: "control" — a user-editable knob the UI renders (KAN-46);
#          "input"   — an image/video/audio/prompt slot resolved by the handler,
#                      not typed by the user;
#          "system"  — managed by the platform (seed policy, output paths).
# type drives the control the UI renders for "control" params.
PARAM_META = {
    "prompt": {"type": "text", "label": "Prompt", "group": "control"},
    "negative_prompt": {"type": "text", "label": "Negative prompt", "group": "control"},
    "steps": {"type": "int", "label": "Steps", "default": 20, "min": 1, "max": 100, "group": "control"},
    "sampler_name": {
        "type": "enum", "label": "Sampler", "group": "control",
        "options": ["euler", "euler_ancestral", "heun", "dpm_2", "dpmpp_2m",
                    "dpmpp_2m_sde", "dpmpp_3m_sde", "dpmpp_sde", "ddim", "uni_pc", "lcm"],
    },
    "scheduler": {
        "type": "enum", "label": "Scheduler", "group": "control",
        "options": ["normal", "karras", "exponential", "sgm_uniform", "simple",
                    "ddim_uniform", "beta"],
    },
    "aspect_ratio": {
        "type": "enum", "label": "Aspect ratio", "group": "control",
        "options": ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)",
                    "3:4 (Portrait Standard)", "4:3 (Standard)",
                    "9:16 (Portrait Widescreen)", "16:9 (Widescreen)",
                    "21:9 (Ultrawide)"],
    },
    "megapixels": {"type": "float", "label": "Megapixels", "default": 1.0, "min": 0.25, "max": 4.0, "group": "control"},
    "width": {"type": "int", "label": "Width", "default": 1024, "min": 256, "max": 4096, "group": "control"},
    "height": {"type": "int", "label": "Height", "default": 1024, "min": 256, "max": 4096, "group": "control"},
    "fps": {"type": "int", "label": "FPS", "default": 24, "min": 1, "max": 60, "group": "control"},
    "duration": {"type": "float", "label": "Duration (s)", "default": 4.0, "min": 1.0, "max": 20.0, "group": "control"},
    "reference_frame_count": {"type": "int", "label": "Reference frames", "default": 1, "min": 1, "max": 200, "group": "control"},
    "controlnet_strength": {"type": "float", "label": "ControlNet strength", "default": 1.0, "min": 0.0, "max": 2.0, "group": "control"},
    "expand_left": {"type": "int", "label": "Expand left (px)", "default": 0, "min": 0, "max": 2048, "group": "control"},
    "expand_right": {"type": "int", "label": "Expand right (px)", "default": 0, "min": 0, "max": 2048, "group": "control"},
    "expand_top": {"type": "int", "label": "Expand top (px)", "default": 0, "min": 0, "max": 2048, "group": "control"},
    "expand_bottom": {"type": "int", "label": "Expand bottom (px)", "default": 0, "min": 0, "max": 2048, "group": "control"},
    "driving_frames": {"type": "int", "label": "Driving frames", "default": 48, "min": 1, "max": 600, "group": "control"},
    "length": {"type": "int", "label": "Output length (frames)", "default": 48, "min": 1, "max": 600, "group": "control"},
    "pose_strength": {"type": "float", "label": "Pose strength", "default": 1.0, "min": 0.0, "max": 2.0, "group": "control"},

    # Handler-resolved slots — present in the schema so the UI can show what a
    # workflow consumes, but not rendered as editable controls.
    "image": {"type": "image", "label": "Image", "group": "input"},
    "ref_image": {"type": "image", "label": "Reference image", "group": "input"},
    "reference_image": {"type": "image", "label": "Colour-match reference", "group": "input"},
    "image2": {"type": "image", "label": "Subject 2", "group": "input"},
    "image3": {"type": "image", "label": "Subject 3", "group": "input"},
    "image4": {"type": "image", "label": "Subject 4", "group": "input"},
    "image5": {"type": "image", "label": "Reference 5", "group": "input"},
    "image6": {"type": "image", "label": "Reference 6", "group": "input"},
    "image7": {"type": "image", "label": "Reference 7", "group": "input"},
    "image8": {"type": "image", "label": "Reference 8", "group": "input"},
    "image9": {"type": "image", "label": "Reference 9", "group": "input"},
    "background_image": {"type": "image", "label": "Background plate", "group": "input"},
    "last_frame": {"type": "image", "label": "Last frame", "group": "input"},
    "ref_video": {"type": "video", "label": "Reference video", "group": "input"},
    "ref_video2": {"type": "video", "label": "Reference video 2", "group": "input"},
    "ref_video3": {"type": "video", "label": "Reference video 3", "group": "input"},
    "ref_audio": {"type": "audio", "label": "Reference audio", "group": "input"},
    "ref_audio2": {"type": "audio", "label": "Reference audio 2", "group": "input"},
    "ref_audio3": {"type": "audio", "label": "Reference audio 3", "group": "input"},
    "driving_video": {"type": "video", "label": "Driving video", "group": "input"},
    "global_prompt": {"type": "text", "label": "Global prompt", "group": "input"},
    "local_prompts": {"type": "text", "label": "Local prompts", "group": "input"},

    # Platform-managed.
    "seed": {"type": "seed", "label": "Seed", "group": "system"},
    "filename_prefix": {"type": "text", "label": "Filename prefix", "group": "system"},
}


def _kind_for(name: str) -> str:
    if name in KIND_OVERRIDES:
        return KIND_OVERRIDES[name]
    if name.startswith("video_"):
        return "video"
    if name.startswith("3d_"):
        return "3d"
    return "image"


def _label_for(name: str) -> str:
    """Human label from the graph file name (best-effort; overridable later)."""
    stem = name
    for prefix in ("image_", "video_", "3d_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return stem.replace("_", " ").strip().title()


# node-map key -> the INJECTION_MAP keys that route through it. One node-map key
# can back several knobs (e.g. the four expand_* sides share one outpaint node),
# so this is a one-to-many index.
def _node_key_to_params() -> dict:
    index: dict[str, list[str]] = {}
    for param, (node_key, _fields) in INJECTION_MAP.items():
        index.setdefault(node_key, []).append(param)
    return index


def _param_schema(param: str) -> dict:
    meta = PARAM_META.get(param, {"type": "text", "label": param.replace("_", " ").title(), "group": "control"})
    return {"key": param, **meta}


@functools.lru_cache(maxsize=1)
def build_registry() -> dict:
    """Derive the full registry, keyed by workflow (graph) name.

    Scans every ``*.map.json`` in the workflow dir; a workflow exposes a knob iff
    its map contains that knob's node-map key. Cached — the map files are static
    at runtime; call ``build_registry.cache_clear()`` in tests that add maps.
    """
    node_index = _node_key_to_params()
    registry: dict[str, dict] = {}

    for fname in sorted(os.listdir(WORKFLOW_DIR)):
        if not fname.endswith(".map.json"):
            continue
        name = fname[: -len(".map.json")]
        with open(os.path.join(WORKFLOW_DIR, fname)) as f:
            node_map = json.load(f)

        params: list[dict] = []
        for node_key in node_map:
            for param in node_index.get(node_key, ()):
                params.append(_param_schema(param))
        # Stable, de-duplicated order (a node key can back several knobs).
        seen = set()
        uniq = [p for p in params if not (p["key"] in seen or seen.add(p["key"]))]
        uniq.sort(key=lambda p: p["key"])

        registry[name] = {
            "name": name,
            "kind": _kind_for(name),
            "label": _label_for(name),
            "params": uniq,
        }
    return registry


# ── merging the hand-authored registries ───────────────────────────────────
#
# Three registries describe workflows, and they are NOT duplicates:
#   this module   — derived from the .map.json files; MECHANICAL, i.e. which
#                   INJECTION_MAP knobs a graph physically exposes.
#   VIDEO_WORKFLOWS — hand-authored; SEMANTIC, i.e. what a workflow NEEDS
#                   (needs_still, max_refs, autogrow_slots). None of that is
#                   derivable from a node map, and autogrow_slots is load-bearing.
#   IMAGE_WORKFLOWS — hand-authored; a txt2img model picker (label/blurb).
#
# Both hand-authored registries are keyed by a workflow *key* ("minimax_h3_r2v")
# whose cfg names a *graph* ("video_minimax_h3_r2v") — the key is what a batch
# spec submits. Merging them onto the derived entries gives the frontend ONE
# endpoint and ONE param shape instead of three, which is why the batch dialog
# needs no per-registry adapter.


def _setting_to_param(spec: dict) -> dict:
    """Convert a VIDEO_WORKFLOWS setting spec into the registry's param shape.

    The video specs carry no explicit type (the backend never needed one), so
    infer it the way the UI must render it.
    """
    if "options" in spec:
        ptype = "enum"
    elif isinstance(spec.get("default"), bool):
        ptype = "bool"
    elif isinstance(spec.get("default"), int):
        ptype = "int"
    elif isinstance(spec.get("default"), float):
        ptype = "float"
    else:
        ptype = "text"
    param = {"key": spec["id"], "type": ptype,
             "label": spec.get("label") or spec["id"], "group": "control"}
    for k in ("default", "min", "max", "step", "options", "help"):
        if k in spec:
            param[k] = spec[k]
    return param


def _hand_authored_by_graph() -> dict[str, dict]:
    """graph name -> the extra facts its hand-authored entry carries."""
    from services.video_service import VIDEO_WORKFLOWS, _public_settings
    from services.image_workflows import IMAGE_WORKFLOWS

    _CAPABILITY_KEYS = (
        "needs_still", "requires_first_frame", "max_refs", "max_ref_videos",
        "max_ref_audios", "background", "locations_as_refs", "driving_video",
        "dual_prompt", "autogrow_slots", "first_frame", "last_frame",
    )
    out: dict[str, dict] = {}
    for key, cfg in VIDEO_WORKFLOWS.items():
        out[cfg["workflow"]] = {
            "workflow_key": key,
            "label": cfg.get("label"),
            "blurb": cfg.get("blurb"),
            "recommended": bool(cfg.get("recommended")),
            "est_seconds": cfg.get("est_seconds"),
            "capabilities": {k: cfg[k] for k in _CAPABILITY_KEYS if k in cfg},
            # For video graphs the *validated* knobs are the settings specs, not
            # every injectable key — _resolve_settings accepts exactly these.
            "control_params": [_setting_to_param(s)
                               for s in _public_settings(cfg.get("settings", []))],
        }
    for key, cfg in IMAGE_WORKFLOWS.items():
        out.setdefault(cfg["workflow"], {}).update({
            "workflow_key": key,
            "label": cfg.get("label"),
            "blurb": cfg.get("blurb"),
            "recommended": bool(cfg.get("recommended")),
            "capabilities": {"supports_size": cfg.get("supports_size", True)},
        })
    return out


def list_workflows(kind: str | None = None) -> list[dict]:
    """Registry entries as a JSON-serialisable list, optionally filtered by kind.

    Entries are the derived schema plus, where one exists, the hand-authored
    entry's key/label/capabilities — so a caller can render controls and submit
    a batch spec from this one payload.
    """
    extras = _hand_authored_by_graph()
    entries = []
    for entry in build_registry().values():
        merged = dict(entry)
        extra = extras.get(entry["name"])
        if extra:
            control = extra.pop("control_params", None)
            merged.update({k: v for k, v in extra.items() if v is not None})
            if control is not None:
                # Keep the derived input/system params (they document what the
                # graph consumes) but let the validated settings own `control`.
                merged["params"] = control + [
                    p for p in entry["params"] if p.get("group") != "control"
                ]
        entries.append(merged)
    if kind:
        entries = [e for e in entries if e["kind"] == kind]
    return sorted(entries, key=lambda e: e["name"])


def exposed_params(workflow_name: str) -> set[str]:
    entry = build_registry().get(workflow_name)
    if entry is None:
        return set()
    return {p["key"] for p in entry["params"]}


def graph_for_batch(kind: str, workflow_key: str | None) -> str | None:
    """Resolve the ComfyUI graph name a batch spec will actually run, or None
    when the kind has no single statically-known graph (validation then falls
    back to the INJECTION_MAP-membership check only). Kept in step with the
    workflow constants in ``job_handlers`` / the workflow key registries."""
    if kind == "asset_img2img":
        return "image_flux2_klein_image_edit_4b_base"
    if kind == "color_match":
        return "image_color_match"
    if kind == "plate_expand":
        return "image_plate_outpaint"
    if kind == "plate_angles":
        return "image_plate_angles_base"
    if kind == "asset_txt2img":
        from services.image_workflows import resolve_workflow_name
        return resolve_workflow_name(workflow_key)
    if kind == "video":
        from services.video_service import VIDEO_WORKFLOWS
        cfg = VIDEO_WORKFLOWS.get(workflow_key)
        return cfg["workflow"] if cfg else None
    return None


def validate_params(kind: str, workflow_key: str | None, params: dict) -> list[str]:
    """Return the list of param keys in ``params`` the chosen workflow cannot
    route. A key is rejected when it is not an ``INJECTION_MAP`` knob at all, or
    (when the graph is statically known) when that graph's map does not expose
    it. Empty list == valid."""
    if not params:
        return []
    graph = graph_for_batch(kind, workflow_key)
    if graph is not None and graph in build_registry():
        allowed = exposed_params(graph)
    else:
        # Kind with no single known graph: fall back to "is it a real knob at
        # all", which still catches typos and dropped/renamed keys.
        allowed = set(INJECTION_MAP)
    return [k for k in params if k not in allowed]

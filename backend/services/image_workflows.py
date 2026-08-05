"""Selectable txt2img workflows for the asset-image ("set image") generator.

Small sibling of video_service.VIDEO_WORKFLOWS: the txt2img popup renders its
model picker from this registry (GET /api/image-workflows) rather than a
hard-coded frontend list, and build_asset_txt2img resolves the ComfyUI graph
name from the chosen key. Only txt2img is registry-driven for now; img2img
still uses its single Flux-2 Klein edit graph.

`supports_size`: the graph takes explicit width×height (Z-Image) vs. deriving
its dimensions from an aspect ratio (Krea2's ResolutionSelector). The handler
always passes both a width/height and a derived aspect_ratio; inject() drops
whichever the chosen workflow's map doesn't expose, so this flag is purely a UI
hint for how to present the size control.
"""

IMAGE_WORKFLOWS = {
    "z_image_turbo": {
        "workflow": "image_z_image_turbo",
        "label": "Z-Image Turbo",
        "blurb": "Fast, versatile default with direct width × height control.",
        "supports_size": True,
        "recommended": True,
    },
    "krea2_turbo": {
        "workflow": "image_krea2_turbo",
        "label": "Krea2 Turbo (2-pass)",
        "blurb": "Photoreal 2-pass finetune (int8 convrot, tuned for 30-series). Sized by aspect ratio.",
        "supports_size": False,
        "recommended": False,
    },
}

DEFAULT_IMAGE_WORKFLOW = "z_image_turbo"


def resolve_workflow_name(workflow_key: str | None) -> str:
    """ComfyUI graph name for a registry key, falling back to the default.

    An unknown key falls back rather than raising: the worker should still
    produce *something* usable rather than dead-letter a job on a stale key.
    """
    cfg = IMAGE_WORKFLOWS.get(workflow_key or DEFAULT_IMAGE_WORKFLOW)
    if cfg is None:
        cfg = IMAGE_WORKFLOWS[DEFAULT_IMAGE_WORKFLOW]
    return cfg["workflow"]


def list_image_workflows() -> list[dict]:
    """The registry as a JSON-serialisable list for the model picker."""
    return [{**cfg, "id": key} for key, cfg in IMAGE_WORKFLOWS.items()]


# Krea2's ResolutionSelector aspect-ratio COMBO options (exact strings ComfyUI
# validates against). The txt2img popup offers width×height presets; map each to
# the nearest aspect so an aspect-driven graph honours the user's size choice.
_ASPECT_OPTIONS = {
    1 / 1: "1:1 (Square)",
    2 / 3: "2:3 (Portrait Photo)",
    3 / 2: "3:2 (Photo)",
    3 / 4: "3:4 (Portrait Standard)",
    4 / 3: "4:3 (Standard)",
    9 / 16: "9:16 (Portrait Widescreen)",
    16 / 9: "16:9 (Widescreen)",
    21 / 9: "21:9 (Ultrawide)",
}


def aspect_ratio_label(width: int | None, height: int | None) -> str | None:
    """Nearest aspect-ratio COMBO label for a width×height, or None if unknown."""
    if not width or not height:
        return None
    ratio = width / height
    nearest = min(_ASPECT_OPTIONS, key=lambda r: abs(r - ratio))
    return _ASPECT_OPTIONS[nearest]

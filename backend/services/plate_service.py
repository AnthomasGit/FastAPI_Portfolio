"""Location background plates (Phase 4, KAN-41).

A *plate* is a wide, character-free establishing render of a Location, generated
once and reused as the background across every scene set there (KAN-42) instead
of re-inventing the environment each time. It is a plain txt2img built from the
location's ``prompt_profile`` plus explicit "empty environment" framing, at a
wide aspect ratio, tagged ``AssetImage(kind="plate")``; the ``location_plate``
job's completion points ``Location.plate_asset_image_id`` at the result.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetImage, JobRecord, Location
from services.prompt_builder import location_prompt

# Wide establishing default (16:9-ish); the z-image workflow exposes width/height.
DEFAULT_PLATE_WIDTH = 1344
DEFAULT_PLATE_HEIGHT = 768

# Appended to the location prompt so the plate is unpopulated scenery — a clean
# background, not a scene. Kept as data so it can be tuned in one place.
PLATE_FRAMING = ("wide establishing shot, empty environment, scenery only, "
                 "no people, no characters, unpopulated, background plate")


def build_plate_prompt(location: Location) -> str:
    return f"{location_prompt(location)}, {PLATE_FRAMING}"


async def generate_location_plate(
    location: Location,
    db: AsyncSession,
    width: int | None = None,
    height: int | None = None,
    workflow: str | None = None,
) -> str:
    """Enqueue a wide, character-free plate render for a location. Returns the
    AssetImage id; the worker runs it and its completion sets the location's
    ``plate_asset_image_id`` (see job_handlers.on_complete_location_plate)."""
    prompt = build_plate_prompt(location)
    width = width or DEFAULT_PLATE_WIDTH
    height = height or DEFAULT_PLATE_HEIGHT

    asset = AssetImage(
        origin_project_id=location.project_id,
        entity_type="location",
        kind="plate",
        prompt=prompt,
        status="queued",
        params={"location_id": location.id, "width": width, "height": height},
    )
    db.add(asset)
    await db.flush()

    job = JobRecord(
        kind="location_plate", status="queued",
        entity_type="asset_image", entity_id=asset.id,
        payload={
            "project_id": location.project_id,
            "entity_type": "location",
            "prompt": prompt,
            "width": width,
            "height": height,
            "workflow": workflow,
            "asset_image_id": asset.id,
            "location_id": location.id,
        },
    )
    db.add(job)
    await db.commit()
    return asset.id


# ── plate expansion / outpaint (KAN-43) ─────────────────────────────────────

# Named expansion presets → per-side pixel amounts. "widen_21_9" pads both
# sides to open a 16:9 plate toward 21:9; the pans reveal one side.
EXPAND_PRESETS = {
    "widen_21_9": {"expand_left": 256, "expand_right": 256},
    "pan_left": {"expand_left": 512},
    "pan_right": {"expand_right": 512},
    "widen": {"expand_left": 256, "expand_right": 256},
}
_SIDE_KEYS = ("expand_left", "expand_right", "expand_top", "expand_bottom")


def resolve_expansion(preset: str | None, explicit: dict | None) -> dict:
    """Turn a preset name and/or explicit per-side amounts into a dict of the
    expand_* pixel amounts. Explicit sides win over the preset. Raises
    ValueError for an unknown preset or when nothing expands (router → 422)."""
    amounts: dict[str, int] = {}
    if preset:
        if preset not in EXPAND_PRESETS:
            raise ValueError(
                f"Unknown expand preset '{preset}'. Options: {sorted(EXPAND_PRESETS)}")
        amounts.update(EXPAND_PRESETS[preset])
    for key in _SIDE_KEYS:
        if explicit and explicit.get(key) is not None:
            amounts[key] = int(explicit[key])
    if not any(amounts.get(k) for k in _SIDE_KEYS):
        raise ValueError("Expansion needs a preset or at least one expand_* amount")
    return amounts


async def expand_location_plate(
    location: Location,
    db: AsyncSession,
    preset: str | None = None,
    amounts: dict | None = None,
    prompt: str | None = None,
) -> str:
    """Enqueue an outpaint pass widening the location's current plate. Returns
    the new AssetImage id, linked back to the source plate via
    ``source_asset_image_id``. Raises ValueError if the location has no plate or
    the expansion is empty/unknown (router → 404/422)."""
    if not location.plate_asset_image_id:
        raise ValueError("Location has no plate to expand")
    expand = resolve_expansion(preset, amounts)

    asset = AssetImage(
        origin_project_id=location.project_id,
        entity_type="location",
        kind="plate",
        prompt=prompt,
        status="queued",
        source_asset_image_id=location.plate_asset_image_id,
        params={"location_id": location.id, "expanded_from": location.plate_asset_image_id,
                "preset": preset, **expand},
    )
    db.add(asset)
    await db.flush()

    job = JobRecord(
        kind="plate_expand", status="queued",
        entity_type="asset_image", entity_id=asset.id,
        payload={
            "project_id": location.project_id,
            "source_asset_image_id": location.plate_asset_image_id,
            "asset_image_id": asset.id,
            "location_id": location.id,
            "prompt": prompt,
            **expand,
        },
    )
    db.add(job)
    await db.commit()
    return asset.id

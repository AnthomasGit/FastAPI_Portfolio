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
from services.prompt_builder import entity_prompt

# Wide establishing default (16:9-ish); the z-image workflow exposes width/height.
DEFAULT_PLATE_WIDTH = 1344
DEFAULT_PLATE_HEIGHT = 768

# Appended to the location prompt so the plate is unpopulated scenery — a clean
# background, not a scene. Kept as data so it can be tuned in one place.
PLATE_FRAMING = ("wide establishing shot, empty environment, scenery only, "
                 "no people, no characters, unpopulated, background plate")


def build_plate_prompt(location: Location) -> str:
    return f"{entity_prompt(location)}, {PLATE_FRAMING}"


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

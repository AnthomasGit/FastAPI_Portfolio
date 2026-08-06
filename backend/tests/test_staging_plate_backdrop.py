"""Phase 4 (KAN-44): a new staging defaults its backdrop to the Location plate."""
import uuid

import pytest

from database import Location, AssetImage, Reference, SceneStaging, scene_locations
from services.staging_service import get_or_create_staging


async def _link_plated_location(db_session, project, scene, name="Hall", plate=True):
    asset_id = None
    if plate:
        asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                           entity_type="location", kind="plate",
                           status="completed", image_url=f"{name}_plate.png")
        db_session.add(asset)
        await db_session.flush()
        asset_id = asset.id
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name=name,
                   plate_asset_image_id=asset_id)
    db_session.add(loc)
    await db_session.flush()
    await db_session.execute(
        scene_locations.insert().values(scene_id=scene.id, location_id=loc.id))
    await db_session.commit()
    return loc, asset_id


@pytest.mark.asyncio
async def test_new_staging_defaults_backdrop_to_plate(db_session, project, scene):
    loc, asset_id = await _link_plated_location(db_session, project, scene)

    staging = await get_or_create_staging(scene.id, db_session)

    assert staging.backdrop_reference_id is not None
    ref = await db_session.get(Reference, staging.backdrop_reference_id)
    assert ref.entity_type == "location" and ref.entity_id == loc.id
    assert ref.asset_image_id == asset_id
    assert ref.role == "backdrop"


@pytest.mark.asyncio
async def test_no_plate_creates_staging_without_backdrop(db_session, project, scene):
    await _link_plated_location(db_session, project, scene, plate=False)
    staging = await get_or_create_staging(scene.id, db_session)
    assert staging.backdrop_reference_id is None


@pytest.mark.asyncio
async def test_existing_explicit_backdrop_left_alone(db_session, project, scene):
    # Pre-existing staging with an explicit, unrelated backdrop.
    explicit = Reference(id=str(uuid.uuid4()), entity_type="location",
                         entity_id="whatever", role="moodboard", url="chosen.png")
    db_session.add(explicit)
    staging = SceneStaging(scene_id=scene.id, backdrop_reference_id=explicit.id)
    db_session.add(staging)
    await db_session.commit()

    # Now the location gets a plate — but the existing choice must not change.
    await _link_plated_location(db_session, project, scene)
    again = await get_or_create_staging(scene.id, db_session)
    assert again.backdrop_reference_id == explicit.id


@pytest.mark.asyncio
async def test_backdrop_reference_deduped_across_scenes(db_session, project, scene):
    """Two scenes sharing one plated location reuse a single backdrop Reference."""
    from database import Scene
    loc, asset_id = await _link_plated_location(db_session, project, scene)
    scene2 = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=2)
    db_session.add(scene2)
    await db_session.flush()
    await db_session.execute(
        scene_locations.insert().values(scene_id=scene2.id, location_id=loc.id))
    await db_session.commit()

    s1 = await get_or_create_staging(scene.id, db_session)
    s2 = await get_or_create_staging(scene2.id, db_session)
    assert s1.backdrop_reference_id == s2.backdrop_reference_id

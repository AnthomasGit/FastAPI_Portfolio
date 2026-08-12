"""Phase 4 (KAN-41): Location background plates — model, endpoint, completion."""
import uuid

import pytest

from database import AssetImage, JobRecord, Location
from services import plate_service
from services.job_handlers import on_complete_location_plate


@pytest.mark.asyncio
async def test_generate_plate_enqueues_wide_character_free_job(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Throne Room",
                   prompt_profile={"environment": ["gothic stone hall"]})
    db_session.add(loc)
    await db_session.commit()

    asset_id = await plate_service.generate_location_plate(loc, db_session)

    asset = await db_session.get(AssetImage, asset_id)
    assert asset.kind == "plate"
    assert asset.entity_type == "location"

    job = (await db_session.execute(
        JobRecord.__table__.select().where(JobRecord.entity_id == asset_id)
    )).first()
    assert job.kind == "location_plate"
    assert job.max_attempts == 1
    # Wide establishing dimensions...
    assert job.payload["width"] == plate_service.DEFAULT_PLATE_WIDTH
    assert job.payload["height"] == plate_service.DEFAULT_PLATE_HEIGHT
    assert job.payload["width"] > job.payload["height"]
    # ...and character-free framing tokens carried in the prompt.
    prompt = job.payload["prompt"].lower()
    assert "no people" in prompt and "no characters" in prompt
    assert "gothic stone hall" in prompt  # profile still contributes
    assert job.payload["location_id"] == loc.id


@pytest.mark.asyncio
async def test_override_dimensions(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Alley")
    db_session.add(loc)
    await db_session.commit()
    asset_id = await plate_service.generate_location_plate(loc, db_session, width=1920, height=816)
    job = (await db_session.execute(
        JobRecord.__table__.select().where(JobRecord.entity_id == asset_id)
    )).first()
    assert (job.payload["width"], job.payload["height"]) == (1920, 816)


@pytest.mark.asyncio
async def test_completion_publishes_a_reference(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Beach")
    db_session.add(loc)
    await db_session.commit()
    asset_id = await plate_service.generate_location_plate(loc, db_session)

    await on_complete_location_plate(
        {"asset_image_id": asset_id, "location_id": loc.id, "image_url": "plate.png"},
        {}, db_session)

    from services.reference_service import newest_asset_image_id
    assert await newest_asset_image_id(db_session, "location", loc.id) == asset_id
    asset = await db_session.get(AssetImage, asset_id)
    assert asset.status == "completed" and asset.image_url == "plate.png"


@pytest.mark.asyncio
async def test_plate_endpoint(client, db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bridge")
    db_session.add(loc)
    await db_session.commit()

    resp = await client.post(f"/api/locations/{loc.id}/plate", json={})
    assert resp.status_code == 202
    assert resp.json()["asset_image_id"]

    missing = await client.post(f"/api/locations/{uuid.uuid4()}/plate", json={})
    assert missing.status_code == 404



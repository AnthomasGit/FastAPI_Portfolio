import os
import uuid
import pytest
import respx
from httpx import Response

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")
os.environ.setdefault("COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
os.makedirs("/tmp/comfy_test_output", exist_ok=True)

from services.comfyui_client import COMFY_API_URL
from database import Reference, AssetImage


# ── txt2img generation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_txt2img_returns_202(client, project, character):
    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(
            "/api/asset-images/generate",
            json={
                "project_id": project.id,
                "entity_type": "characters",
                "prompt": "A test character image",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "asset_image_id" in data


@pytest.mark.asyncio
async def test_generate_txt2img_applies_custom_width_height(client, project, character, db_session):
    # Generation now enqueues a JobRecord (the worker submits later), so
    # width/height are carried on the job payload rather than injected inline.
    resp = await client.post(
        "/api/asset-images/generate",
        json={
            "project_id": project.id,
            "entity_type": "characters",
            "prompt": "A test character image",
            "width": 1280,
            "height": 720,
        },
    )
    assert resp.status_code == 202
    asset_id = resp.json()["asset_image_id"]

    from sqlalchemy import select
    from database import JobRecord
    job = (
        await db_session.execute(
            select(JobRecord).where(JobRecord.entity_id == asset_id)
        )
    ).scalars().first()
    assert job is not None
    assert job.kind == "asset_txt2img"
    assert job.payload["width"] == 1280
    assert job.payload["height"] == 720


@pytest.mark.asyncio
async def test_generate_txt2img_rejects_missing_prompt(client, project):
    resp = await client.post(
        "/api/asset-images/generate",
        json={"project_id": project.id, "entity_type": "characters"},
    )
    assert resp.status_code == 422


# ── img2img from reference ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_img2img_from_reference(client, project, character, db_session):
    ref = Reference(
        entity_type="character",
        entity_id=character.id,
        role="primary",
        url="test_ref.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(
            "/api/asset-images/generate",
            json={
                "project_id": project.id,
                "entity_type": "characters",
                "prompt": "Edit this image",
                "source_reference_id": ref.id,
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "asset_image_id" in data


# ── img2img from existing asset image ─────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_img2img_from_asset_image(client, project, character, db_session):
    src = AssetImage(
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="completed",
        image_url="source.png",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)

    os.makedirs("/tmp/comfy_test_output", exist_ok=True)
    with open("/tmp/comfy_test_output/source.png", "wb") as f:
        f.write(b"fake-png-data")

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(
            "/api/asset-images/generate",
            json={
                "project_id": project.id,
                "entity_type": "characters",
                "prompt": "Edit this image",
                "source_asset_image_id": src.id,
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "asset_image_id" in data


# ── Invalid entity_type ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_invalid_entity_type_returns_422(client, project):
    resp = await client.post(
        "/api/asset-images/generate",
        json={
            "project_id": project.id,
            "entity_type": "scenes",
            "prompt": "test",
        },
    )
    assert resp.status_code == 422


# ── Assign-asset creates a pool Reference (no global primary) ─────────────

@pytest.mark.asyncio
async def test_assign_asset_creates_pool_reference(client, project, character, db_session):
    """No global primary: assign-asset adds/updates a pool reference keyed by
    asset_image_id. Setting it as *this scene's* primary is a separate step
    (PUT .../links/{entity_type}/{entity_id}) done by the caller."""
    asset = AssetImage(
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="completed",
        image_url="assets/test/characters/job123_00001_.png",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.post(
        f"/api/characters/{character.id}/assign-asset",
        json={"asset_image_id": asset.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_type"] == "character"
    assert data["entity_id"] == character.id
    assert data["role"] == "moodboard"
    assert data["url"] == asset.image_url
    assert data["asset_image_id"] == asset.id

    # Second call on the SAME asset image upserts (doesn't duplicate)
    resp2 = await client.post(
        f"/api/characters/{character.id}/assign-asset",
        json={"asset_image_id": asset.id},
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == data["id"]

    from sqlalchemy import select
    result = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "character",
            Reference.entity_id == character.id,
        )
    )
    refs = result.scalars().all()
    assert len(refs) == 1


@pytest.mark.asyncio
async def test_assign_different_asset_images_creates_separate_references(
    client, project, character, db_session
):
    asset1 = AssetImage(origin_project_id=project.id, entity_type="character",
                        kind="txt2img", status="completed", image_url="a.png")
    asset2 = AssetImage(origin_project_id=project.id, entity_type="character",
                        kind="txt2img", status="completed", image_url="b.png")
    db_session.add_all([asset1, asset2])
    await db_session.commit()
    await db_session.refresh(asset1)
    await db_session.refresh(asset2)

    r1 = await client.post(f"/api/characters/{character.id}/assign-asset",
                           json={"asset_image_id": asset1.id})
    r2 = await client.post(f"/api/characters/{character.id}/assign-asset",
                           json={"asset_image_id": asset2.id})
    assert r1.json()["id"] != r2.json()["id"]

    from sqlalchemy import select
    result = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "character",
            Reference.entity_id == character.id,
        )
    )
    assert len(result.scalars().all()) == 2


# ── Assign-asset rejects incomplete asset ─────────────────────────────────

@pytest.mark.asyncio
async def test_assign_asset_rejects_incomplete(client, project, character, db_session):
    asset = AssetImage(
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="processing",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.post(
        f"/api/characters/{character.id}/assign-asset",
        json={"asset_image_id": asset.id},
    )
    assert resp.status_code == 422


# ── Picker query filters ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_picker_filters_by_entity_type(client, project, db_session):
    char_asset = AssetImage(
        origin_project_id=project.id, entity_type="character", kind="txt2img",
        status="completed", image_url="c.png",
    )
    loc_asset = AssetImage(
        origin_project_id=project.id, entity_type="location", kind="txt2img",
        status="completed", image_url="l.png",
    )
    db_session.add_all([char_asset, loc_asset])
    await db_session.commit()

    resp = await client.get(
        f"/api/asset-images?entity_type=characters&project_id={project.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["entity_type"] == "character"


# ── Status polling ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_status_transitions(client, project, db_session):
    # The status endpoint now reflects the owning job's state onto the row
    # (queued -> queued, running -> processing) instead of polling ComfyUI.
    from database import JobRecord

    asset = AssetImage(
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="queued",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    job = JobRecord(
        kind="asset_txt2img",
        status="queued",
        entity_type="asset_image",
        entity_id=asset.id,
        payload={"asset_image_id": asset.id},
    )
    db_session.add(job)
    await db_session.commit()

    # queued job -> "queued"
    resp = await client.get(f"/api/asset-images/{asset.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"

    # running job -> "processing"
    job.status = "running"
    await db_session.commit()
    resp = await client.get(f"/api/asset-images/{asset.id}")
    assert resp.json()["status"] == "processing"


# ── 404 for nonexistent asset ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nonexistent_asset_returns_404(client):
    resp = await client.get(f"/api/asset-images/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_location_generation_attaches_profile_tokens(client, project, db_session, location):
    """Generating a location image with entity_id prepends the location's fixed
    profile tokens to the prompt (KAN-41)."""
    from sqlalchemy import select
    from database import JobRecord
    location.prompt_profile = {"environment": ["gothic stone hall"], "lighting": ["torchlight"]}
    await db_session.commit()

    resp = await client.post(
        "/api/asset-images/generate",
        json={
            "project_id": project.id,
            "entity_type": "locations",
            "entity_id": location.id,
            "prompt": "empty wide shot",
        },
    )
    assert resp.status_code == 202
    asset_id = resp.json()["asset_image_id"]
    job = (await db_session.execute(
        select(JobRecord).where(JobRecord.entity_id == asset_id))).scalars().first()
    prompt = job.payload["prompt"]
    assert "gothic stone hall" in prompt and "torchlight" in prompt  # tokens attached
    assert "empty wide shot" in prompt                                # user prompt kept


@pytest.mark.asyncio
async def test_delete_asset_image(client, db_session, project):
    from sqlalchemy import select
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed")
    db_session.add(asset)
    await db_session.commit()

    resp = await client.delete(f"/api/asset-images/{asset.id}")
    assert resp.status_code == 204
    gone = (await db_session.execute(
        select(AssetImage).where(AssetImage.id == asset.id))).scalars().first()
    assert gone is None

    assert (await client.delete(f"/api/asset-images/{uuid.uuid4()}")).status_code == 404

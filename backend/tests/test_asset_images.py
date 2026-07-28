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


# ── Assign-asset upserts primary Reference ─────────────────────────────────

@pytest.mark.asyncio
async def test_assign_asset_upserts_primary_reference(client, project, character, db_session):
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
    assert data["role"] == "primary"
    assert data["url"] == asset.image_url
    assert data["asset_image_id"] == asset.id

    # Second call upserts (doesn't create a second Reference)
    resp2 = await client.post(
        f"/api/characters/{character.id}/assign-asset",
        json={"asset_image_id": asset.id},
    )
    assert resp2.status_code == 200

    from sqlalchemy import select
    result = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "character",
            Reference.entity_id == character.id,
            Reference.role == "primary",
        )
    )
    refs = result.scalars().all()
    assert len(refs) == 1


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
    asset = AssetImage(
        origin_project_id=project.id,
        entity_type="character",
        kind="txt2img",
        status="queued",
        prompt_id=str(uuid.uuid4()),
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{asset.prompt_id}").mock(
            return_value=Response(200, json={
                asset.prompt_id: {
                    "status": {"status_str": "completed"},
                    "outputs": {"9": {"images": [{"filename": "test.png", "type": "output"}]}},
                }
            })
        )

        resp = await client.get(f"/api/asset-images/{asset.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"


# ── 404 for nonexistent asset ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nonexistent_asset_returns_404(client):
    resp = await client.get(f"/api/asset-images/{uuid.uuid4()}")
    assert resp.status_code == 404

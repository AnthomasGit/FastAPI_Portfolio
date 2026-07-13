import os
import uuid
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch, AsyncMock
from httpx import Response
import respx

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from services.comfyui_client import COMFY_API_URL
from database import Asset3D, JobRecord, Reference
from sqlalchemy import select


# ── Generate: success path ─────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("services.asset3d_service.load_workflow")
@patch("services.asset3d_service.load_node_map")
async def test_generate_mesh_creates_asset_and_job_record(
    mock_load_node_map, mock_load_workflow, client, character, db_session,
):
    mock_load_workflow.return_value = {"1": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {
        "image_node": "1", "seed_node": "2", "output_node": "3",
    }

    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(
            "/api/assets3d/generate",
            json={"entity_type": "character", "entity_id": character.id},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "asset3d_id" in data

        result = await db_session.execute(
            select(Asset3D).where(Asset3D.id == data["asset3d_id"])
        )
        asset = result.scalars().first()
        assert asset is not None
        assert asset.status == "mesh_processing"

        job_result = await db_session.execute(
            select(JobRecord).where(JobRecord.entity_id == asset.id)
        )
        job = job_result.scalars().first()
        assert job is not None
        assert job.job_type == "mesh"


# ── Poll: state transitions ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_returns_queued_unchanged_when_not_in_history(
    client, db_session, project,
):
    prompt_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id, prompt_id=prompt_id, model_name="test", query="test",
        job_type="mesh", status="processing",
    )
    db_session.add(job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_processing", mesh_job_id=job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={})
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "mesh_processing"


@pytest.mark.asyncio
async def test_poll_transitions_processing_to_ready(
    client, db_session, project,
):
    prompt_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id, prompt_id=prompt_id, model_name="test", query="test",
        job_type="mesh", status="processing",
    )
    db_session.add(job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_processing", mesh_job_id=job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {
                    "status": {"status_str": "completed"},
                    "outputs": {"9": {"images": [{"filename": "test.glb"}]}},
                }
            })
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "mesh_ready"


@pytest.mark.asyncio
async def test_poll_transitions_processing_to_failed(
    client, db_session, project,
):
    prompt_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id, prompt_id=prompt_id, model_name="test", query="test",
        job_type="mesh", status="processing",
    )
    db_session.add(job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_processing", mesh_job_id=job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {
                    "status": {"status_str": "error"},
                    "outputs": {},
                }
            })
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "mesh_failed"


@pytest.mark.asyncio
async def test_poll_returns_terminal_status_unchanged(
    client, db_session, project,
):
    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_ready",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.get(f"/api/assets3d/{asset.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "mesh_ready"


# ── Generate: validation / rejection ───────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_location_rejected_422(client):
    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "location", "entity_id": "any"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_invalid_entity_type_rejected_422(client):
    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "scene", "entity_id": "any"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_missing_entity_rejected_404(client):
    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "character", "entity_id": "nonexistent-id"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_missing_reference_rejected_422(
    client, character,
):
    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "character", "entity_id": character.id},
    )
    assert resp.status_code == 422


# ── Retry ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("services.asset3d_service.load_workflow")
@patch("services.asset3d_service.load_node_map")
async def test_retry_mesh_failed_transitions_to_processing(
    mock_load_node_map, mock_load_workflow, client, db_session, project,
):
    mock_load_workflow.return_value = {"1": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {
        "image_node": "1", "seed_node": "2", "output_node": "3",
    }

    ref = Reference(
        entity_type="character", entity_id="e1",
        role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    old_job_id = str(uuid.uuid4())
    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_failed", source_reference_id=ref.id, mesh_job_id=old_job_id,
        error="previous failure",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(f"/api/assets3d/{asset.id}/retry")
        assert resp.status_code == 202

        result = await db_session.execute(
            select(Asset3D).where(Asset3D.id == asset.id)
        )
        updated = result.scalars().first()
        assert updated.status == "mesh_processing"
        assert updated.mesh_job_id != old_job_id
        assert updated.error is None


@pytest.mark.asyncio
async def test_retry_non_failed_rejected_409(client, db_session, project):
    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_ready",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.post(f"/api/assets3d/{asset.id}/retry")
    assert resp.status_code == 409


# ── Timeout ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_timeout_sets_failed(client, db_session, project):
    old_job_id = str(uuid.uuid4())
    old_job = JobRecord(
        job_id=old_job_id,
        model_name="test",
        query="test",
        job_type="mesh",
        status="processing",
        created_at=datetime.utcnow() - timedelta(minutes=31),
    )
    db_session.add(old_job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_processing", mesh_job_id=old_job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.get(f"/api/assets3d/{asset.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "mesh_failed"
    assert data["error"] == "Mesh generation timed out"


# ── List ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_assets3d_returns_project_assets(
    client, db_session, project,
):
    a1 = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
    )
    a2 = Asset3D(
        project_id=project.id, entity_type="prop", entity_id="e2",
    )
    db_session.add_all([a1, a2])
    await db_session.commit()

    resp = await client.get(f"/api/projects/{project.id}/assets3d")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ── Delete ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_asset3d_returns_204(client, db_session, project):
    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.delete(f"/api/assets3d/{asset.id}")
    assert resp.status_code == 204

    result = await db_session.execute(
        select(Asset3D).where(Asset3D.id == asset.id)
    )
    assert result.scalars().first() is None


# ── GLB proxy ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_mesh_file_returns_404_for_nonexistent(client):
    resp = await client.get(f"/api/assets3d/{uuid.uuid4()}/mesh")
    assert resp.status_code == 404


# ── Per-job JobRecord ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("services.asset3d_service.load_workflow")
@patch("services.asset3d_service.load_node_map")
async def test_retry_creates_new_job_record(
    mock_load_node_map, mock_load_workflow, client, db_session, project,
):
    mock_load_workflow.return_value = {"1": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {
        "image_node": "1", "seed_node": "2", "output_node": "3",
    }

    ref = Reference(
        entity_type="character", entity_id="e1",
        role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    old_job_id = str(uuid.uuid4())
    old_job = JobRecord(
        job_id=old_job_id, model_name="test", query="test",
        job_type="mesh", status="failed",
    )
    db_session.add(old_job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_failed", source_reference_id=ref.id, mesh_job_id=old_job_id,
        error="previous failure",
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    prompt_id = str(uuid.uuid4())
    with respx.mock:
        respx.post(f"{COMFY_API_URL}/prompt").mock(
            return_value=Response(200, json={"prompt_id": prompt_id})
        )

        resp = await client.post(f"/api/assets3d/{asset.id}/retry")
        assert resp.status_code == 202

        result = await db_session.execute(
            select(Asset3D).where(Asset3D.id == asset.id)
        )
        updated = result.scalars().first()
        assert updated.mesh_job_id != old_job_id

        job_result = await db_session.execute(
            select(JobRecord).where(JobRecord.job_id == updated.mesh_job_id)
        )
        new_job = job_result.scalars().first()
        assert new_job is not None
        assert new_job.job_type == "mesh"
        assert new_job.job_id != old_job_id

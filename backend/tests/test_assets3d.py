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
async def test_generate_mesh_creates_asset_and_job_record(
    client, character, db_session,
):
    # Generation now enqueues a mesh job (the worker submits later).
    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()

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
    assert asset.status == "queued"

    job_result = await db_session.execute(
        select(JobRecord).where(JobRecord.entity_id == asset.id)
    )
    job = job_result.scalars().first()
    assert job is not None
    assert job.kind == "mesh"
    assert job.status == "queued"
    assert job.payload["asset3d_id"] == asset.id


# ── Generate: per-entity-type workflow routing (recorded on the job payload) ──

@pytest.mark.asyncio
async def test_generate_routes_character_to_trellis2(client, character, db_session):
    ref = Reference(
        entity_type="character", entity_id=character.id, role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()

    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "character", "entity_id": character.id},
    )
    assert resp.status_code == 202
    job = (
        await db_session.execute(
            select(JobRecord).where(JobRecord.entity_id == resp.json()["asset3d_id"])
        )
    ).scalars().first()
    assert job.payload["workflow_name"] == "MeshWithTexturing_6steps_example"
    assert job.payload["dual_output"] is True


@pytest.mark.asyncio
async def test_generate_routes_prop_to_triposplat(client, prop, db_session):
    ref = Reference(entity_type="prop", entity_id=prop.id, role="primary", url="test.png")
    db_session.add(ref)
    await db_session.commit()

    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "prop", "entity_id": prop.id},
    )
    assert resp.status_code == 202
    job = (
        await db_session.execute(
            select(JobRecord).where(JobRecord.entity_id == resp.json()["asset3d_id"])
        )
    ).scalars().first()
    assert job.payload["workflow_name"] == "3d_triposplat_image_to_gaussian_splat"
    assert job.payload["dual_output"] is False


# ── Poll: reflects job state onto the row (worker drives progress) ─────────

async def _add_mesh_job_and_asset(db_session, project, *, entity_type, job_status,
                                  job_id=None, error=None):
    job_id = job_id or str(uuid.uuid4())
    job = JobRecord(
        job_id=job_id, kind="mesh", model_name="test", query="test",
        job_type="mesh", status=job_status, error=error,
        entity_type="asset3d",
    )
    db_session.add(job)
    asset = Asset3D(
        project_id=project.id, entity_type=entity_type, entity_id="e1",
        status="mesh_processing",
    )
    db_session.add(asset)
    await db_session.flush()
    job.entity_id = asset.id
    await db_session.commit()
    await db_session.refresh(asset)
    return asset


@pytest.mark.asyncio
async def test_poll_maps_running_job_to_mesh_processing(client, db_session, project):
    asset = await _add_mesh_job_and_asset(
        db_session, project, entity_type="character", job_status="running")
    resp = await client.get(f"/api/assets3d/{asset.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "mesh_processing"


@pytest.mark.asyncio
async def test_poll_maps_queued_job_to_queued(client, db_session, project):
    asset = await _add_mesh_job_and_asset(
        db_session, project, entity_type="character", job_status="queued")
    # Force the asset to a non-terminal, non-processing state first.
    asset.status = "queued"
    await db_session.commit()
    resp = await client.get(f"/api/assets3d/{asset.id}")
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_poll_maps_failed_job_to_mesh_failed(client, db_session, project):
    asset = await _add_mesh_job_and_asset(
        db_session, project, entity_type="character",
        job_status="failed", error="ComfyUI error")
    resp = await client.get(f"/api/assets3d/{asset.id}")
    body = resp.json()
    assert body["status"] == "mesh_failed"
    assert body["error"] == "ComfyUI error"


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
async def test_on_complete_mesh_character_sets_ready_with_both_meshes(db_session, project):
    from services.asset3d_service import on_complete_mesh
    job_id = str(uuid.uuid4())
    asset = Asset3D(project_id=project.id, entity_type="character", entity_id="e1",
                    status="mesh_processing")
    db_session.add(asset)
    await db_session.commit()

    out_dir = os.path.join("/tmp/comfy_test_output", "meshes", project.id, "characters")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, job_id)
    open(f"{base}_Textured_00001_.glb", "wb").close()
    open(f"{base}_WhiteMesh_00001_.glb", "wb").close()

    payload = {"asset3d_id": asset.id, "project_id": project.id,
               "entity_type": "character", "job_id": job_id, "dual_output": True}
    await on_complete_mesh(payload, {}, db_session)
    await db_session.refresh(asset)
    assert asset.status == "mesh_ready"
    assert asset.mesh_url.endswith("_Textured_00001_.glb")
    assert asset.white_mesh_url.endswith("_WhiteMesh_00001_.glb")


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output_prop")
async def test_on_complete_mesh_prop_single_output(db_session, project):
    from services.asset3d_service import on_complete_mesh
    job_id = str(uuid.uuid4())
    asset = Asset3D(project_id=project.id, entity_type="prop", entity_id="p1",
                    status="mesh_processing")
    db_session.add(asset)
    await db_session.commit()

    out_dir = os.path.join("/tmp/comfy_test_output_prop", "meshes", project.id, "props")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, f"{job_id}_00001_.glb"), "wb").close()

    payload = {"asset3d_id": asset.id, "project_id": project.id,
               "entity_type": "prop", "job_id": job_id, "dual_output": False}
    await on_complete_mesh(payload, {}, db_session)
    await db_session.refresh(asset)
    assert asset.status == "mesh_ready"
    assert asset.mesh_url.endswith(f"{job_id}_00001_.glb")
    assert asset.white_mesh_url is None


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output_missing")
async def test_on_complete_mesh_no_file_raises(db_session, project):
    """A 'completed' run that produced no file (graph rejected at validation)
    must raise so the worker records a failure instead of a false mesh_ready."""
    from services.asset3d_service import on_complete_mesh
    asset = Asset3D(project_id=project.id, entity_type="character", entity_id="e1",
                    status="mesh_processing")
    db_session.add(asset)
    await db_session.commit()

    payload = {"asset3d_id": asset.id, "project_id": project.id,
               "entity_type": "character", "job_id": str(uuid.uuid4()), "dual_output": True}
    with pytest.raises(RuntimeError):
        await on_complete_mesh(payload, {}, db_session)


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
async def test_retry_mesh_failed_transitions_to_queued(client, db_session, project):
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

    resp = await client.post(f"/api/assets3d/{asset.id}/retry")
    assert resp.status_code == 202

    result = await db_session.execute(
        select(Asset3D).where(Asset3D.id == asset.id)
    )
    updated = result.scalars().first()
    # Reset + re-enqueued; the worker will move it back to mesh_processing.
    assert updated.status == "queued"
    assert updated.mesh_job_id is None
    assert updated.error is None

    new_job = (
        await db_session.execute(
            select(JobRecord).where(JobRecord.entity_id == asset.id,
                                    JobRecord.status == "queued")
        )
    ).scalars().first()
    assert new_job is not None and new_job.kind == "mesh"


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
async def test_poll_reflects_timed_out_job_as_failed(client, db_session, project):
    # The worker enforces JOB_POLL_TIMEOUT and fails the job; poll_asset then
    # reflects that failure (with the job's error) onto the row.
    asset = await _add_mesh_job_and_asset(
        db_session, project, entity_type="character",
        job_status="failed", error="poll_timeout")
    resp = await client.get(f"/api/assets3d/{asset.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "mesh_failed"
    assert data["error"] == "poll_timeout"


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
async def test_retry_creates_new_job_record(client, db_session, project):
    ref = Reference(
        entity_type="character", entity_id="e1",
        role="tpose", url="test.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    old_job_id = str(uuid.uuid4())
    old_job = JobRecord(
        job_id=old_job_id, kind="mesh", model_name="test", query="test",
        job_type="mesh", status="failed", entity_type="asset3d",
    )
    db_session.add(old_job)

    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
        status="mesh_failed", source_reference_id=ref.id, mesh_job_id=old_job_id,
        error="previous failure",
    )
    db_session.add(asset)
    await db_session.flush()
    old_job.entity_id = asset.id
    await db_session.commit()
    await db_session.refresh(asset)

    resp = await client.post(f"/api/assets3d/{asset.id}/retry")
    assert resp.status_code == 202

    # A fresh queued mesh job now exists for this asset, distinct from the old one.
    new_job = (
        await db_session.execute(
            select(JobRecord).where(
                JobRecord.entity_id == asset.id, JobRecord.status == "queued"
            )
        )
    ).scalars().first()
    assert new_job is not None
    assert new_job.kind == "mesh"
    assert new_job.job_id != old_job_id


# ── Mesh from an asset-image-backed reference (OUTPUT-dir file must be staged) ──

@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
@patch("services.asset3d_service.remove_background", side_effect=Exception("no rembg"))
async def test_mesh_from_asset_image_reference_is_staged_into_input(
    mock_rmbg, client, character, db_session,
):
    # Source staging still happens at enqueue (it can raise a caller error), so
    # the OUTPUT-dir file is copied into INPUT and its flat name lands on the
    # job payload's source_url — the worker injects it later.
    input_dir = os.environ["COMFY_INPUT_DIR"]
    output_dir = "/tmp/comfy_test_output"
    rel = f"assets/{character.project_id}/characters/{character.id}_00001_.png"
    out_path = os.path.join(output_dir, rel)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(b"\x89PNG\r\n fake image bytes")

    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="primary", url=rel, asset_image_id="asset-img-1",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "character", "entity_id": character.id},
    )
    assert resp.status_code == 202

    staged = f"{ref.id}_source.png"
    assert os.path.exists(os.path.join(input_dir, staged))

    result = await db_session.execute(
        select(Asset3D).where(Asset3D.id == resp.json()["asset3d_id"])
    )
    asset = result.scalars().first()
    assert asset.status == "queued"
    job = (
        await db_session.execute(select(JobRecord).where(JobRecord.entity_id == asset.id))
    ).scalars().first()
    assert job.payload["source_url"] == staged


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
@patch("services.asset3d_service.load_node_map")
@patch("services.asset3d_service.load_workflow")
async def test_mesh_missing_asset_image_file_returns_422(
    mock_load_workflow, mock_load_node_map, client, character, db_session,
):
    mock_load_workflow.return_value = {"2": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {"image_node": "2", "seed_node": "7", "output_node": "10"}

    # reference points at an asset-image file that does not exist on disk
    ref = Reference(
        entity_type="character", entity_id=character.id, role="primary",
        url=f"assets/{character.project_id}/characters/missing_00001_.png",
        asset_image_id="asset-img-2",
    )
    db_session.add(ref)
    await db_session.commit()

    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "character", "entity_id": character.id},
    )
    assert resp.status_code == 422
    assert "missing" in resp.json()["detail"].lower()

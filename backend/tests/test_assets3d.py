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


# ── Generate: per-entity-type workflow routing ─────────────────────────────

@pytest.mark.asyncio
@patch("services.asset3d_service.submit", new_callable=AsyncMock)
@patch("services.asset3d_service.load_node_map")
@patch("services.asset3d_service.load_workflow")
async def test_generate_routes_character_to_trellis2(
    mock_load_workflow, mock_load_node_map, mock_submit, client, character, db_session,
):
    mock_load_workflow.return_value = {"1": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {"image_node": "1", "seed_node": "2", "output_node": "3"}
    mock_submit.return_value = "prompt-1"

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
    mock_load_workflow.assert_called_with("MeshWithTexturing_6steps_example")
    mock_load_node_map.assert_called_with("MeshWithTexturing_6steps_example")


@pytest.mark.asyncio
@patch("services.asset3d_service.submit", new_callable=AsyncMock)
@patch("services.asset3d_service.load_node_map")
@patch("services.asset3d_service.load_workflow")
async def test_generate_routes_prop_to_triposplat(
    mock_load_workflow, mock_load_node_map, mock_submit, client, prop, db_session,
):
    mock_load_workflow.return_value = {"1": {"inputs": {"image": ""}}}
    mock_load_node_map.return_value = {"image_node": "1", "seed_node": "2", "output_node": "3"}
    mock_submit.return_value = "prompt-2"

    ref = Reference(entity_type="prop", entity_id=prop.id, role="primary", url="test.png")
    db_session.add(ref)
    await db_session.commit()

    resp = await client.post(
        "/api/assets3d/generate",
        json={"entity_type": "prop", "entity_id": prop.id},
    )
    assert resp.status_code == 202
    mock_load_workflow.assert_called_with("3d_triposplat_image_to_gaussian_splat")
    mock_load_node_map.assert_called_with("3d_triposplat_image_to_gaussian_splat")


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
@patch("routers.assets3d.optimize_web_mesh", new_callable=AsyncMock)
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
async def test_poll_transitions_processing_to_ready(
    mock_optimize, client, db_session, project,
):
    # Reaching mesh_ready fires the real auto-optimize BackgroundTask, which
    # opens its own production SessionLocal — bypassing this test's DB
    # override entirely and touching the real database. Mock it out; the
    # web-optimize trigger itself isn't what this test is checking.
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

    # mesh_ready now requires an actual textured GLB on disk (poll_asset no
    # longer trusts ComfyUI's "completed" status alone — see the
    # false-ready regression this guards against).
    out_dir = os.path.join("/tmp/comfy_test_output", "meshes", project.id, "characters")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, job_id)
    open(f"{base}_Textured_00001_.glb", "wb").close()
    open(f"{base}_WhiteMesh_00001_.glb", "wb").close()

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
        body = resp.json()
        assert body["status"] == "mesh_ready"
        assert body["mesh_url"].endswith("_Textured_00001_.glb")
        assert body["white_mesh_url"].endswith("_WhiteMesh_00001_.glb")


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output_missing")
async def test_poll_completed_with_no_file_marks_failed(
    client, db_session, project,
):
    """ComfyUI can report status_str='completed' after silently rejecting an
    invalid graph at validation (e.g. an out-of-range node input) and writing
    no output. Confirm poll_asset treats that as a failure, not mesh_ready."""
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
                prompt_id: {"status": {"status_str": "completed"}, "outputs": {}}
            })
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "mesh_failed"
        assert body["mesh_url"] is None


@pytest.mark.asyncio
@patch("routers.assets3d.optimize_web_mesh", new_callable=AsyncMock)
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output_prop")
async def test_poll_prop_single_output_reaches_ready_without_white_mesh(
    mock_optimize, client, db_session, project,
):
    """TripoSplat's SaveGLB writes one file (no _Textured/_WhiteMesh split).
    A prop asset must reach mesh_ready off that single match, with
    white_mesh_url left None rather than failing for lack of a second file.

    Mocks the auto-optimize BackgroundTask (see the same note on
    test_poll_transitions_processing_to_ready) since reaching mesh_ready
    fires it for real otherwise."""
    prompt_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id, prompt_id=prompt_id, model_name="test", query="test",
        job_type="mesh", status="processing",
    )
    db_session.add(job)

    asset = Asset3D(
        project_id=project.id, entity_type="prop", entity_id="p1",
        status="mesh_processing", mesh_job_id=job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    out_dir = os.path.join("/tmp/comfy_test_output_prop", "meshes", project.id, "props")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, f"{job_id}_00001_.glb"), "wb").close()

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {"status": {"status_str": "completed"}, "outputs": {}}
            })
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "mesh_ready"
        assert body["mesh_url"].endswith(f"{job_id}_00001_.glb")
        assert body["white_mesh_url"] is None


@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output_prop_missing")
async def test_poll_prop_completed_with_no_file_marks_failed(
    client, db_session, project,
):
    """Same false-ready guard as characters, exercised on the single-output
    (dual_output=False) discovery path used for props."""
    prompt_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = JobRecord(
        job_id=job_id, prompt_id=prompt_id, model_name="test", query="test",
        job_type="mesh", status="processing",
    )
    db_session.add(job)

    asset = Asset3D(
        project_id=project.id, entity_type="prop", entity_id="p1",
        status="mesh_processing", mesh_job_id=job_id,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    with respx.mock:
        respx.get(f"{COMFY_API_URL}/history/{prompt_id}").mock(
            return_value=Response(200, json={
                prompt_id: {"status": {"status_str": "completed"}, "outputs": {}}
            })
        )

        resp = await client.get(f"/api/assets3d/{asset.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "mesh_failed"
        assert body["mesh_url"] is None


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


# ── Mesh from an asset-image-backed reference (OUTPUT-dir file must be staged) ──

@pytest.mark.asyncio
@patch("services.asset3d_service.COMFY_OUTPUT_DIR", "/tmp/comfy_test_output")
@patch("services.asset3d_service.remove_background", side_effect=Exception("no rembg"))
@patch("services.asset3d_service.submit", new_callable=AsyncMock)
@patch("services.asset3d_service.load_node_map")
@patch("services.asset3d_service.load_workflow")
async def test_mesh_from_asset_image_reference_is_staged_into_input(
    mock_load_workflow, mock_load_node_map, mock_submit, mock_rmbg,
    client, character, db_session,
):
    mock_load_workflow.return_value = {"2": {"inputs": {"image": ""}, "class_type": "LoadImage"}}
    mock_load_node_map.return_value = {"image_node": "2", "seed_node": "7", "output_node": "10"}
    mock_submit.return_value = "prompt-staged"

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

    # The OUTPUT-dir file was copied into INPUT under a flat filename ...
    staged = f"{ref.id}_source.png"
    assert os.path.exists(os.path.join(input_dir, staged))
    # ... and that flat filename (not the OUTPUT subfolder path) was injected.
    submitted_workflow = mock_submit.call_args.args[0]
    assert submitted_workflow["2"]["inputs"]["image"] == staged

    result = await db_session.execute(
        select(Asset3D).where(Asset3D.id == resp.json()["asset3d_id"])
    )
    assert result.scalars().first().status == "mesh_processing"


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

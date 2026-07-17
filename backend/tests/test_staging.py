import os
import uuid
import json

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

import pytest
from sqlalchemy import select
from database import Asset3D, SceneStaging, SceneCapture


# ── Staging upsert-on-read ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_staging_creates_empty_on_first_read(client, scene):
    resp = await client.get(f"/api/scenes/{scene.id}/staging")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scene_id"] == scene.id
    assert data["camera"] is None
    assert data["blockout"] is None
    assert data["placements"] is None
    assert data["backdrop_reference_id"] is None
    assert "id" in data


@pytest.mark.asyncio
async def test_get_staging_returns_same_on_subsequent_calls(client, scene):
    resp1 = await client.get(f"/api/scenes/{scene.id}/staging")
    resp2 = await client.get(f"/api/scenes/{scene.id}/staging")
    assert resp1.json()["id"] == resp2.json()["id"]


@pytest.mark.asyncio
async def test_get_staging_returns_404_for_nonexistent_scene(client):
    resp = await client.get(f"/api/scenes/{uuid.uuid4()}/staging")
    assert resp.status_code == 404


# ── PUT staging ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_put_staging_updates_camera_blockout_placements(client, scene):
    payload = {
        "camera": {"position": [1, 2, 3], "target": [0, 0, 0], "fov": 45, "aspect": 1.777},
        "blockout": [{"id": "b1", "kind": "floor", "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [4, 0.1, 4]}}],
        "placements": [],
    }
    resp = await client.put(f"/api/scenes/{scene.id}/staging", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["camera"]["position"] == [1, 2, 3]
    assert len(data["blockout"]) == 1
    assert data["blockout"][0]["kind"] == "floor"


@pytest.mark.asyncio
async def test_put_staging_roundtrips_backdrop_transform(client, scene):
    payload = {
        "backdrop_transform": {"pos": [1, 2, 3], "rot": [0, 0, 0], "scale": [4, 3, 1]},
    }
    resp = await client.put(f"/api/scenes/{scene.id}/staging", json=payload)
    assert resp.status_code == 200
    assert resp.json()["backdrop_transform"]["pos"] == [1, 2, 3]

    get_resp = await client.get(f"/api/scenes/{scene.id}/staging")
    assert get_resp.json()["backdrop_transform"]["scale"] == [4, 3, 1]


@pytest.mark.asyncio
async def test_put_staging_validates_asset3d_id_belongs_to_project(client, db_session, scene, project):
    other_project_id = str(uuid.uuid4())
    asset = Asset3D(
        project_id=other_project_id, entity_type="character", entity_id="e1",
    )
    db_session.add(asset)
    await db_session.commit()

    payload = {
        "placements": [{"id": "p1", "asset3d_id": asset.id, "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [1, 1, 1]}}],
    }
    resp = await client.put(f"/api/scenes/{scene.id}/staging", json=payload)
    assert resp.status_code == 422
    assert "not found or does not belong to this project" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_staging_accepts_valid_asset3d_id(client, db_session, scene, project):
    asset = Asset3D(
        project_id=project.id, entity_type="character", entity_id="e1",
    )
    db_session.add(asset)
    await db_session.commit()

    payload = {
        "placements": [{"id": "p1", "asset3d_id": asset.id, "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [1, 1, 1]}}],
    }
    resp = await client.put(f"/api/scenes/{scene.id}/staging", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["placements"]) == 1
    assert data["placements"][0]["asset3d_id"] == asset.id


# ── Capture creation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_capture_freeze_snapshot_and_returns_201(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    # PUT some blockout+placements first
    payload = {
        "blockout": [{"id": "b1", "kind": "floor", "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [4, 0.1, 4]}}],
    }
    await client.put(f"/api/scenes/{scene.id}/staging", json=payload)

    depth_content = b"fake-png-bytes"
    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={
            "depth_map": ("depth.png", depth_content, "image/png"),
        },
        data={
            "camera": json.dumps({"position": [1, 2, 3], "target": [0, 0, 0]}),
            "width": 1024,
            "height": 576,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["staging_id"] == staging.id
    assert data["width"] == 1024
    assert data["height"] == 576
    assert data["depth_map_url"].startswith("depth_")

    # Verify snapshot was frozen with the blockout
    snapshot = data["staging_snapshot"]
    assert len(snapshot["blockout"]) == 1
    assert snapshot["blockout"][0]["kind"] == "floor"


@pytest.mark.asyncio
async def test_create_capture_with_edge_map(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={
            "depth_map": ("depth.png", b"depth-data", "image/png"),
            "edge_map": ("edge.png", b"edge-data", "image/png"),
        },
        data={
            "camera": json.dumps({"position": [0, 0, 0], "target": [0, 0, -1]}),
            "width": 640,
            "height": 480,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["edge_map_url"] is not None
    assert data["edge_map_url"].startswith("edge_")


@pytest.mark.asyncio
async def test_create_capture_with_color_map(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={
            "depth_map": ("depth.png", b"depth-data", "image/png"),
            "color_map": ("color.png", b"color-data", "image/png"),
        },
        data={
            "camera": json.dumps({"position": [0, 0, 5], "target": [0, 0, 0]}),
            "width": 1024,
            "height": 576,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["color_map_url"] is not None
    assert data["color_map_url"].startswith("color_")

    color_resp = await client.get(f"/api/captures/{data['id']}/color")
    assert color_resp.status_code == 200
    assert color_resp.content == b"color-data"


@pytest.mark.asyncio
async def test_create_capture_without_color_map(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={"depth_map": ("depth.png", b"depth-data", "image/png")},
        data={"camera": "{}", "width": 100, "height": 100},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["color_map_url"] is None

    color_resp = await client.get(f"/api/captures/{data['id']}/color")
    assert color_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_capture_with_all_maps(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={
            "depth_map": ("depth.png", b"depth-data", "image/png"),
            "color_map": ("color.png", b"color-data", "image/png"),
            "normal_map": ("normal.png", b"normal-data", "image/png"),
            "seg_map": ("seg.png", b"seg-data", "image/png"),
        },
        data={"camera": "{}", "width": 1024, "height": 576},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["normal_map_url"].startswith("normal_")
    assert data["seg_map_url"].startswith("seg_")

    normal_resp = await client.get(f"/api/captures/{data['id']}/normal")
    assert normal_resp.status_code == 200
    assert normal_resp.content == b"normal-data"

    seg_resp = await client.get(f"/api/captures/{data['id']}/seg")
    assert seg_resp.status_code == 200
    assert seg_resp.content == b"seg-data"


@pytest.mark.asyncio
async def test_create_capture_depth_only_leaves_maps_null(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={"depth_map": ("depth.png", b"depth-data", "image/png")},
        data={"camera": "{}", "width": 100, "height": 100},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["normal_map_url"] is None
    assert data["seg_map_url"] is None

    assert (await client.get(f"/api/captures/{data['id']}/normal")).status_code == 404
    assert (await client.get(f"/api/captures/{data['id']}/seg")).status_code == 404


# ── List captures ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_captures_returns_empty_when_no_staging(client, scene):
    resp = await client.get(f"/api/scenes/{scene.id}/staging/captures")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_captures_returns_captures(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    # Create two captures via the API
    for _ in range(2):
        await client.post(
            f"/api/scenes/{scene.id}/staging/captures",
            files={"depth_map": ("d.png", b"data", "image/png")},
            data={"camera": "{}", "width": 100, "height": 100},
        )

    resp = await client.get(f"/api/scenes/{scene.id}/staging/captures")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ── Depth map proxy ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_depth_map_returns_png(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={"depth_map": ("d.png", b"fake-png-content", "image/png")},
        data={"camera": "{}", "width": 100, "height": 100},
    )
    capture = resp.json()

    depth_resp = await client.get(f"/api/captures/{capture['id']}/depth")
    assert depth_resp.status_code == 200
    assert depth_resp.content == b"fake-png-content"


@pytest.mark.asyncio
async def test_get_depth_map_returns_404(client):
    resp = await client.get(f"/api/captures/{uuid.uuid4()}/depth")
    assert resp.status_code == 404


# ── Delete capture ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_capture_returns_204(client, scene, db_session):
    staging = SceneStaging(scene_id=scene.id)
    db_session.add(staging)
    await db_session.commit()

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/captures",
        files={"depth_map": ("d.png", b"data", "image/png")},
        data={"camera": "{}", "width": 100, "height": 100},
    )
    capture = resp.json()

    del_resp = await client.delete(f"/api/captures/{capture['id']}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_capture_returns_404(client):
    resp = await client.delete(f"/api/captures/{uuid.uuid4()}")
    assert resp.status_code == 404

import os
import uuid

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

import pytest
from database import Asset3D, Scene


# ── Create save ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_save_snapshots_current_staging(client, scene):
    payload = {
        "camera": {"position": [1, 2, 3], "target": [0, 0, 0], "fov": 45, "aspect": 1.777},
        "blockout": [{"id": "b1", "kind": "floor", "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [4, 0.1, 4]}}],
        "placements": [],
    }
    await client.put(f"/api/scenes/{scene.id}/staging", json=payload)

    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/saves", json={"name": "wide shot"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "wide shot"
    assert data["scene_id"] == scene.id
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_save_rejects_empty_name(client, scene):
    resp = await client.post(
        f"/api/scenes/{scene.id}/staging/saves", json={"name": "   "}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_save_returns_404_for_nonexistent_scene(client):
    resp = await client.post(
        f"/api/scenes/{uuid.uuid4()}/staging/saves", json={"name": "x"}
    )
    assert resp.status_code == 404


# ── List saves (per-scene scoping) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_saves_is_scoped_to_scene(client, db_session, scene, project):
    other_scene = Scene(
        id=str(uuid.uuid4()), project_id=project.id, scene_number=2, slugline="Other"
    )
    db_session.add(other_scene)
    await db_session.commit()

    await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "mine"})
    await client.post(
        f"/api/scenes/{other_scene.id}/staging/saves", json={"name": "theirs"}
    )

    resp = await client.get(f"/api/scenes/{scene.id}/staging/saves")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "mine"

    other_resp = await client.get(f"/api/scenes/{other_scene.id}/staging/saves")
    other_data = other_resp.json()
    assert len(other_data) == 1
    assert other_data[0]["name"] == "theirs"


@pytest.mark.asyncio
async def test_list_saves_empty_for_scene_without_saves(client, scene):
    resp = await client.get(f"/api/scenes/{scene.id}/staging/saves")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Restore ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restore_applies_save_to_staging(client, db_session, scene, project):
    asset = Asset3D(project_id=project.id, entity_type="character", entity_id="e1")
    db_session.add(asset)
    await db_session.commit()

    saved_state = {
        "camera": {"position": [5, 5, 5], "target": [0, 1, 0], "fov": 45, "aspect": 1.777},
        "blockout": [{"id": "b1", "kind": "box", "transform": {"pos": [1, 0, 1], "rot": [0, 0, 0], "scale": [1, 1, 1]}}],
        "placements": [{"id": "p1", "asset3d_id": asset.id, "transform": {"pos": [2, 0, 2], "rot": [0, 0, 0], "scale": [1, 1, 1]}}],
    }
    await client.put(f"/api/scenes/{scene.id}/staging", json=saved_state)
    save = (
        await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "v1"})
    ).json()

    # Mutate the staging afterwards
    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={"camera": {"position": [9, 9, 9]}, "blockout": [], "placements": []},
    )

    resp = await client.post(f"/api/staging-saves/{save['id']}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["camera"]["position"] == [5, 5, 5]
    assert len(data["blockout"]) == 1
    assert data["placements"][0]["transform"]["pos"] == [2, 0, 2]


@pytest.mark.asyncio
async def test_restore_overwrites_fields_empty_in_save(client, scene):
    # Save taken with no camera/backdrop set
    save = (
        await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "empty"})
    ).json()

    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={"camera": {"position": [9, 9, 9]}},
    )

    resp = await client.post(f"/api/staging-saves/{save['id']}/restore")
    assert resp.status_code == 200
    assert resp.json()["camera"] is None


@pytest.mark.asyncio
async def test_restore_fails_when_saved_asset_deleted(client, db_session, scene, project):
    asset = Asset3D(project_id=project.id, entity_type="character", entity_id="e1")
    db_session.add(asset)
    await db_session.commit()

    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={"placements": [{"id": "p1", "asset3d_id": asset.id, "transform": {"pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [1, 1, 1]}}]},
    )
    save = (
        await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "v1"})
    ).json()

    await client.put(f"/api/scenes/{scene.id}/staging", json={"placements": []})
    await db_session.delete(asset)
    await db_session.commit()

    resp = await client.post(f"/api/staging-saves/{save['id']}/restore")
    assert resp.status_code == 400
    assert "not found or does not belong" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_restore_returns_404_for_nonexistent_save(client):
    resp = await client.post(f"/api/staging-saves/{uuid.uuid4()}/restore")
    assert resp.status_code == 404


# ── Overwrite ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overwrite_replaces_save_contents(client, scene):
    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={"camera": {"position": [1, 1, 1]}, "blockout": [], "placements": []},
    )
    save = (
        await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "slot"})
    ).json()

    # Stage a different layout, then overwrite the save with it
    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={
            "camera": {"position": [7, 7, 7]},
            "blockout": [{"id": "b1", "kind": "box", "transform": {"pos": [3, 0, 3], "rot": [0, 0, 0], "scale": [1, 1, 1]}}],
            "placements": [],
        },
    )
    resp = await client.put(f"/api/staging-saves/{save['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == save["id"]
    assert data["name"] == "slot"

    # Wreck the staging, restore, and the overwritten layout comes back
    await client.put(
        f"/api/scenes/{scene.id}/staging",
        json={"camera": {"position": [0, 0, 0]}, "blockout": [], "placements": []},
    )
    restored = (await client.post(f"/api/staging-saves/{save['id']}/restore")).json()
    assert restored["camera"]["position"] == [7, 7, 7]
    assert len(restored["blockout"]) == 1
    assert restored["blockout"][0]["transform"]["pos"] == [3, 0, 3]


@pytest.mark.asyncio
async def test_overwrite_returns_404_for_nonexistent_save(client):
    resp = await client.put(f"/api/staging-saves/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── Delete ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_save_returns_204(client, scene):
    save = (
        await client.post(f"/api/scenes/{scene.id}/staging/saves", json={"name": "x"})
    ).json()

    resp = await client.delete(f"/api/staging-saves/{save['id']}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/scenes/{scene.id}/staging/saves")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_save_returns_404(client):
    resp = await client.delete(f"/api/staging-saves/{uuid.uuid4()}")
    assert resp.status_code == 404

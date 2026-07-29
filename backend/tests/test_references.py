import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import Reference, Character
from services.reference_service import delete_entity_references


# ── Polymorphic CRUD ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_reference_for_scene(client, scene):
    resp = await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "ref.png", "role": "moodboard"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_type"] == "scene"
    assert data["entity_id"] == scene.id
    assert data["role"] == "moodboard"
    assert data["url"] == "ref.png"


@pytest.mark.asyncio
async def test_create_reference_for_character(client, character):
    resp = await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "char.png", "role": "primary"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_type"] == "character"
    assert data["entity_id"] == character.id
    assert data["role"] == "primary"


@pytest.mark.asyncio
async def test_create_reference_for_location(client, location):
    resp = await client.post(
        f"/api/locations/{location.id}/references",
        json={"url": "loc.png", "role": "backdrop"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_type"] == "location"
    assert data["entity_id"] == location.id


@pytest.mark.asyncio
async def test_create_reference_for_prop(client, prop):
    resp = await client.post(
        f"/api/props/{prop.id}/references",
        json={"url": "prop.png", "role": "texture_ref"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_type"] == "prop"
    assert data["entity_id"] == prop.id


@pytest.mark.asyncio
async def test_create_reference_nonexistent_entity_returns_404(client):
    resp = await client.post(
        f"/api/characters/nonexistent-id/references",
        json={"url": "x.png", "role": "primary"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_references(client, scene):
    await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "a.png", "role": "moodboard"},
    )
    await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "b.png", "role": "primary"},
    )
    resp = await client.get(f"/api/scenes/{scene.id}/references")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_list_references_other_entity_not_included(client, scene, character):
    await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "a.png", "role": "moodboard"},
    )
    await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "b.png", "role": "primary"},
    )
    resp = await client.get(f"/api/scenes/{scene.id}/references")
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_update_reference(client, scene):
    create_resp = await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "old.png", "role": "moodboard"},
    )
    ref_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/references/{ref_id}",
        json={"role": "primary", "description": "Updated desc", "sort_order": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "primary"
    assert data["description"] == "Updated desc"
    assert data["sort_order"] == 1


@pytest.mark.asyncio
async def test_delete_reference(client, scene):
    create_resp = await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "del.png", "role": "moodboard"},
    )
    ref_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/references/{ref_id}")
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/scenes/{scene.id}/references")
    assert len(list_resp.json()) == 0


# ── Background removal restore (DELETE) ──────────────────────────────────

@pytest.mark.asyncio
async def test_restore_background_clears_processed_url(client, db_session, scene):
    create_resp = await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "orig.png", "role": "primary"},
    )
    ref_id = create_resp.json()["id"]

    # Simulate a prior background removal.
    ref = await db_session.get(Reference, ref_id)
    ref.processed_url = "cutout.png"
    await db_session.commit()

    resp = await client.delete(f"/api/references/{ref_id}/remove-background")
    assert resp.status_code == 200
    assert resp.json()["processed_url"] is None

    refreshed = await db_session.get(Reference, ref_id)
    assert refreshed.processed_url is None


@pytest.mark.asyncio
async def test_restore_background_missing_reference_returns_404(client):
    resp = await client.delete("/api/references/nonexistent-id/remove-background")
    assert resp.status_code == 404


# ── Upload validation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_rejects_non_image(client):
    resp = await client.post(
        "/api/uploads",
        files={"file": ("test.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 422


# ── Cascade delete ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cascade_delete_references_on_character_delete(client, db_session, character):
    await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "r1.png", "role": "primary"},
    )
    await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "r2.png", "role": "moodboard"},
    )

    await client.delete(f"/api/characters/{character.id}")

    remaining = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "character",
            Reference.entity_id == character.id,
        )
    )
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_cascade_delete_references_on_location_delete(client, db_session, location):
    await client.post(
        f"/api/locations/{location.id}/references",
        json={"url": "r1.png", "role": "backdrop"},
    )
    await client.delete(f"/api/locations/{location.id}")
    remaining = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "location",
            Reference.entity_id == location.id,
        )
    )
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_cascade_delete_references_on_prop_delete(client, db_session, prop):
    await client.post(
        f"/api/props/{prop.id}/references",
        json={"url": "r1.png", "role": "texture_ref"},
    )
    await client.delete(f"/api/props/{prop.id}")
    remaining = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "prop",
            Reference.entity_id == prop.id,
        )
    )
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_cascade_delete_references_on_scene_delete(client, db_session, scene):
    await client.post(
        f"/api/scenes/{scene.id}/references",
        json={"url": "r1.png", "role": "moodboard"},
    )
    await client.delete(f"/api/scenes/{scene.id}")
    remaining = await db_session.execute(
        select(Reference).where(
            Reference.entity_type == "scene",
            Reference.entity_id == scene.id,
        )
    )
    assert remaining.scalars().all() == []


# ── Derived reference_url in CharacterResponse ───────────────────────────

@pytest.mark.asyncio
async def test_character_response_derives_reference_url(client, db_session, project):
    # Create character with reference_url via shim
    create_resp = await client.post(
        f"/api/projects/{project.id}/characters",
        json={"name": "Shim Char", "reference_url": "shim.png"},
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert data["reference_url"] == "shim.png"

    char_id = data["id"]

    # List includes derived reference_url
    list_resp = await client.get(f"/api/projects/{project.id}/characters")
    chars = list_resp.json()
    char = next(c for c in chars if c["id"] == char_id)
    assert char["reference_url"] == "shim.png"


@pytest.mark.asyncio
async def test_character_response_no_reference_url(client, project):
    create_resp = await client.post(
        f"/api/projects/{project.id}/characters",
        json={"name": "No Ref"},
    )
    data = create_resp.json()
    assert data["reference_url"] is None


@pytest.mark.asyncio
async def test_character_update_shim_upserts_reference(client, project):
    create_resp = await client.post(
        f"/api/projects/{project.id}/characters",
        json={"name": "Update Shim"},
    )
    char_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/characters/{char_id}",
        json={"reference_url": "updated.png"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["reference_url"] == "updated.png"

    # Update the primary reference
    update_resp2 = await client.put(
        f"/api/characters/{char_id}",
        json={"reference_url": "updated2.png"},
    )
    assert update_resp2.json()["reference_url"] == "updated2.png"


# ── Invalid entity_type ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_entity_type_returns_422(client):
    resp = await client.get("/api/invalid/some-id/references")
    assert resp.status_code == 422


# ── Primary reference is unique per entity ───────────────────────────────
# A character can wear different clothing per scene; the scene's source of
# truth is scene_X.reference_id (already one-per-scene). Entity-level
# role='primary' is the single canonical default those per-scene picks start
# from — it must never be allowed to duplicate.

async def _primaries(client, character):
    refs = (await client.get(f"/api/characters/{character.id}/references")).json()
    return [r for r in refs if r["role"] == "primary"]


@pytest.mark.asyncio
async def test_creating_second_primary_demotes_first(client, character):
    first = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "a.png", "role": "primary"},
    )).json()

    second = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "b.png", "role": "primary"},
    )).json()

    primaries = await _primaries(client, character)
    assert len(primaries) == 1
    assert primaries[0]["id"] == second["id"]

    refreshed_first = (await client.get(f"/api/characters/{character.id}/references")).json()
    demoted = next(r for r in refreshed_first if r["id"] == first["id"])
    assert demoted["role"] == "moodboard"


@pytest.mark.asyncio
async def test_updating_role_to_primary_demotes_existing_primary(client, character):
    first = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "a.png", "role": "primary"},
    )).json()
    second = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "b.png", "role": "moodboard"},
    )).json()

    resp = await client.put(f"/api/references/{second['id']}", json={"role": "primary"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "primary"

    primaries = await _primaries(client, character)
    assert len(primaries) == 1
    assert primaries[0]["id"] == second["id"]

    refreshed = (await client.get(f"/api/characters/{character.id}/references")).json()
    assert next(r for r in refreshed if r["id"] == first["id"])["role"] == "moodboard"


@pytest.mark.asyncio
async def test_updating_role_away_from_primary_does_not_touch_others(client, character):
    """A no-op-adjacent update (role stays non-primary) must not trigger dedup."""
    first = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "a.png", "role": "primary"},
    )).json()
    second = (await client.post(
        f"/api/characters/{character.id}/references",
        json={"url": "b.png", "role": "moodboard"},
    )).json()

    await client.put(f"/api/references/{second['id']}", json={"description": "test"})

    primaries = await _primaries(client, character)
    assert len(primaries) == 1
    assert primaries[0]["id"] == first["id"]


@pytest.mark.asyncio
async def test_double_assign_asset_image_keeps_single_primary(client, character, project, db_session):
    from database import AssetImage

    async def make_completed_asset():
        asset = AssetImage(
            id=str(uuid.uuid4()), origin_project_id=project.id, entity_type="character",
            kind="txt2img", image_url=f"{uuid.uuid4()}.png", status="completed",
        )
        db_session.add(asset)
        await db_session.commit()
        return asset.id

    asset1_id = await make_completed_asset()
    r1 = await client.post(f"/api/characters/{character.id}/assign-asset", json={"asset_image_id": asset1_id})
    assert r1.status_code == 200

    asset2_id = await make_completed_asset()
    r2 = await client.post(f"/api/characters/{character.id}/assign-asset", json={"asset_image_id": asset2_id})
    assert r2.status_code == 200

    primaries = await _primaries(client, character)
    assert len(primaries) == 1
    assert primaries[0]["asset_image_id"] == asset2_id


@pytest.mark.asyncio
async def test_enforce_single_primary_helper_directly(db_session, character):
    from services.reference_service import enforce_single_primary

    r1 = Reference(id=str(uuid.uuid4()), entity_type="character", entity_id=character.id,
                   role="primary", url="a.png")
    r2 = Reference(id=str(uuid.uuid4()), entity_type="character", entity_id=character.id,
                   role="primary", url="b.png")
    db_session.add_all([r1, r2])
    await db_session.commit()

    await enforce_single_primary(db_session, "character", character.id, r2.id)
    await db_session.commit()

    result = await db_session.execute(
        select(Reference).where(Reference.entity_id == character.id, Reference.role == "primary")
    )
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].id == r2.id

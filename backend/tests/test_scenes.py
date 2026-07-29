import uuid
from datetime import datetime, timedelta
import pytest
import pytest_asyncio
from sqlalchemy import select

from database import Scene, Character, Reference, scene_characters


@pytest_asyncio.fixture
async def older_ref(db_session, character):
    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="moodboard", url="knight_older.png",
        created_at=datetime.utcnow() - timedelta(hours=1),
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)
    return ref


@pytest_asyncio.fixture
async def newer_ref(db_session, character, older_ref):
    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="moodboard", url="knight_newer.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)
    return ref


@pytest_asyncio.fixture
async def tpose_ref(db_session, character):
    ref = Reference(
        entity_type="character", entity_id=character.id,
        role="tpose", url="knight_tpose.png",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)
    return ref


# ── Link ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_link_character_creates_row(client, scene, character, db_session):
    resp = await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    assert resp.status_code == 200
    data = resp.json()
    links = data["character_links"]
    assert len(links) == 1
    assert links[0]["entity_id"] == character.id

    rows = await db_session.execute(
        select(scene_characters).where(scene_characters.c.scene_id == scene.id)
    )
    assert len(rows.all()) == 1


@pytest.mark.asyncio
async def test_link_is_idempotent(client, scene, character, db_session):
    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    resp = await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    assert resp.status_code == 200
    rows = await db_session.execute(
        select(scene_characters).where(scene_characters.c.scene_id == scene.id)
    )
    assert len(rows.all()) == 1


@pytest.mark.asyncio
async def test_link_defaults_to_newest_reference(client, scene, character, older_ref, newer_ref):
    """No global primary — a newly-linked scene defaults to the asset's most
    recently added reference (per-scene picks override this via reference_id)."""
    resp = await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    assert resp.status_code == 200
    link = resp.json()["character_links"][0]
    assert link["reference_id"] == newer_ref.id
    assert link["reference_url"] == "knight_newer.png"


@pytest.mark.asyncio
async def test_link_with_explicit_reference(client, scene, character, tpose_ref):
    resp = await client.post(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": tpose_ref.id},
    )
    assert resp.status_code == 200
    assert resp.json()["character_links"][0]["reference_id"] == tpose_ref.id


@pytest.mark.asyncio
async def test_link_unknown_scene_404(client, character):
    resp = await client.post(f"/api/scenes/{uuid.uuid4()}/links/characters/{character.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_link_cross_project_422(client, scene, db_session):
    # a character that belongs to a different project
    from database import Project
    other = Project(id=str(uuid.uuid4()), title="Other", idea="x")
    db_session.add(other)
    await db_session.flush()
    foreign_char = Character(id=str(uuid.uuid4()), project_id=other.id, name="Intruder")
    db_session.add(foreign_char)
    await db_session.commit()

    resp = await client.post(f"/api/scenes/{scene.id}/links/characters/{foreign_char.id}")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_entity_type_422(client, scene, character):
    resp = await client.post(f"/api/scenes/{scene.id}/links/widgets/{character.id}")
    assert resp.status_code == 422


# ── Set per-scene reference ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_reference_updates_and_clears(client, scene, character, older_ref, tpose_ref):
    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")

    resp = await client.put(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": tpose_ref.id},
    )
    assert resp.status_code == 200
    assert resp.json()["character_links"][0]["reference_id"] == tpose_ref.id

    resp = await client.put(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["character_links"][0]["reference_id"] is None


@pytest.mark.asyncio
async def test_set_reference_foreign_ref_422(client, scene, character, db_session):
    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    # reference that belongs to a different character
    other_char = Character(id=str(uuid.uuid4()), project_id=scene.project_id, name="Other")
    db_session.add(other_char)
    await db_session.flush()
    foreign_ref = Reference(
        entity_type="character", entity_id=other_char.id, role="primary", url="x.png",
    )
    db_session.add(foreign_ref)
    await db_session.commit()

    resp = await client.put(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": foreign_ref.id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_reference_no_link_404(client, scene, character, tpose_ref):
    resp = await client.put(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": tpose_ref.id},
    )
    assert resp.status_code == 404


# ── Unlink ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unlink_removes_row(client, scene, character, db_session):
    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    resp = await client.delete(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    assert resp.status_code == 204

    rows = await db_session.execute(
        select(scene_characters).where(scene_characters.c.scene_id == scene.id)
    )
    assert len(rows.all()) == 0

    # second delete is a 404
    resp = await client.delete(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    assert resp.status_code == 404


# ── Per-scene reference is isolated per scene ────────────────────────────────

@pytest.mark.asyncio
async def test_same_character_different_reference_per_scene(
    client, project, character, older_ref, tpose_ref, db_session,
):
    scene_a = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1, slugline="A")
    scene_b = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=2, slugline="B")
    db_session.add_all([scene_a, scene_b])
    await db_session.commit()

    await client.post(
        f"/api/scenes/{scene_a.id}/links/characters/{character.id}",
        json={"reference_id": older_ref.id},
    )
    await client.post(
        f"/api/scenes/{scene_b.id}/links/characters/{character.id}",
        json={"reference_id": tpose_ref.id},
    )

    proj = (await client.get(f"/api/projects/{project.id}")).json()
    by_scene = {s["id"]: s for s in proj["scenes"]}
    assert by_scene[scene_a.id]["character_links"][0]["reference_id"] == older_ref.id
    assert by_scene[scene_b.id]["character_links"][0]["reference_id"] == tpose_ref.id


@pytest.mark.asyncio
async def test_scenes_list_exposes_links(client, project, scene, character, older_ref):
    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}")
    scenes = (await client.get(f"/api/projects/{project.id}/scenes")).json()
    target = next(s for s in scenes if s["id"] == scene.id)
    assert target["character_links"][0]["entity_id"] == character.id
    assert target["character_links"][0]["reference_url"] == "knight_older.png"
    assert target["character_links"][0]["is_processed"] is False


@pytest.mark.asyncio
async def test_link_is_processed_reflects_background_removal(client, scene, character, db_session):
    """A background-removed reference's is_processed must flip to True so the
    client knows reference_url is now the (input-dir-servable) processed_url,
    not the raw asset-image path — getLinkThumbUrl depends on this to avoid
    showing a stale, non-cutout thumbnail."""
    ref = Reference(
        entity_type="character", entity_id=character.id, role="moodboard",
        url="assets/proj/characters/x_00001_.png", asset_image_id="asset-1",
    )
    db_session.add(ref)
    await db_session.commit()
    await db_session.refresh(ref)

    resp = await client.post(
        f"/api/scenes/{scene.id}/links/characters/{character.id}",
        json={"reference_id": ref.id},
    )
    link = resp.json()["character_links"][0]
    assert link["is_processed"] is False
    assert link["reference_url"] == "assets/proj/characters/x_00001_.png"

    ref.processed_url = "cutout.png"
    await db_session.commit()

    resp2 = await client.get(f"/api/scenes/{scene.id}")
    link2 = resp2.json()["character_links"][0]
    assert link2["is_processed"] is True
    assert link2["reference_url"] == "cutout.png"

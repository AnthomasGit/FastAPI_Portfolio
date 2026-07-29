import uuid
from unittest.mock import patch, AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_and_list_shot(client, scene):
    r = await client.post(
        f"/api/scenes/{scene.id}/shots",
        json={"shot_number": "1A", "shot_size": "WS", "angle": "High",
              "movement": "Static", "description": "Establishing shot"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["shot_number"] == "1A"
    assert body["scene_id"] == scene.id
    assert body["still"] is None

    r = await client.get(f"/api/scenes/{scene.id}/shots")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_create_shot_appends_sort_order(client, scene):
    for n in ("1A", "1B", "1C"):
        await client.post(f"/api/scenes/{scene.id}/shots", json={"shot_number": n})
    shots = (await client.get(f"/api/scenes/{scene.id}/shots")).json()
    assert [s["sort_order"] for s in shots] == [0, 1, 2]
    assert [s["shot_number"] for s in shots] == ["1A", "1B", "1C"]


async def test_update_shot_partial(client, scene):
    created = (await client.post(f"/api/scenes/{scene.id}/shots",
                                 json={"shot_number": "1A", "shot_size": "WS"})).json()
    r = await client.put(f"/api/shots/{created['id']}", json={"shot_size": "CU"})
    assert r.status_code == 200
    body = r.json()
    assert body["shot_size"] == "CU"
    assert body["shot_number"] == "1A"  # untouched field preserved


async def test_update_missing_shot_404(client):
    r = await client.put(f"/api/shots/{uuid.uuid4()}", json={"shot_size": "CU"})
    assert r.status_code == 404


async def test_delete_shot(client, scene):
    created = (await client.post(f"/api/scenes/{scene.id}/shots", json={"shot_number": "1A"})).json()
    r = await client.delete(f"/api/shots/{created['id']}")
    assert r.status_code == 204
    assert (await client.get(f"/api/scenes/{scene.id}/shots")).json() == []


async def test_reorder_shots(client, scene):
    ids = []
    for n in ("1A", "1B", "1C"):
        ids.append((await client.post(f"/api/scenes/{scene.id}/shots", json={"shot_number": n})).json()["id"])
    reordered = [ids[2], ids[0], ids[1]]
    r = await client.put(f"/api/scenes/{scene.id}/shots/reorder", json={"shot_ids": reordered})
    assert r.status_code == 200
    assert [s["id"] for s in r.json()] == reordered


async def test_shots_scene_not_found(client):
    r = await client.get(f"/api/scenes/{uuid.uuid4()}/shots")
    assert r.status_code == 404


async def test_generate_shot_list_mocks_llm(client, scene):
    fake = [
        {"shot_number": "1A", "shot_size": "WS", "angle": "High", "movement": "Static",
         "description": "Establishing", "equipment": "Tripod", "audio_notes": "Room tone"},
        {"shot_number": "1B", "shot_size": "CU", "angle": "Eye-Level", "movement": "Static",
         "description": "Face", "equipment": "Tripod", "audio_notes": "Lavalier"},
    ]
    with patch("services.shot_service.ai_service.generate_shot_list",
               new=AsyncMock(return_value=fake)):
        r = await client.post(f"/api/scenes/{scene.id}/shots/generate")
    assert r.status_code == 200
    shots = r.json()
    assert len(shots) == 2
    assert shots[0]["shot_number"] == "1A"
    assert shots[0]["equipment"] == "Tripod"
    # AI draft never attaches a still.
    assert all(s["still"] is None for s in shots)


async def test_generate_appends_after_existing(client, scene):
    await client.post(f"/api/scenes/{scene.id}/shots", json={"shot_number": "MANUAL"})
    with patch("services.shot_service.ai_service.generate_shot_list",
               new=AsyncMock(return_value=[{"shot_number": "1A"}])):
        await client.post(f"/api/scenes/{scene.id}/shots/generate")
    shots = (await client.get(f"/api/scenes/{scene.id}/shots")).json()
    assert [s["shot_number"] for s in shots] == ["MANUAL", "1A"]


async def test_attaching_still_populates_still_on_response(client, scene, db_session):
    """Setting generated_image_id must return the nested still on the same call."""
    from database import GeneratedImage
    gi = GeneratedImage(id=str(uuid.uuid4()), scene_id=scene.id, project_id=scene.project_id,
                        kind="beauty", status="completed", image_url="still.png")
    db_session.add(gi)
    await db_session.commit()

    created = (await client.post(f"/api/scenes/{scene.id}/shots", json={"shot_number": "1A"})).json()
    assert created["still"] is None

    r = await client.put(f"/api/shots/{created['id']}", json={"generated_image_id": gi.id})
    assert r.status_code == 200
    body = r.json()
    assert body["generated_image_id"] == gi.id
    assert body["still"] is not None
    assert body["still"]["id"] == gi.id


async def test_scene_entity_link_exposes_asset_image_id(client, scene, character, db_session):
    """The shared SceneEntityLink change must serialize on the scene path."""
    from database import Reference, AssetImage
    ai = AssetImage(id=str(uuid.uuid4()), entity_type="character", kind="txt2img",
                    image_url="gen.png", status="completed")
    db_session.add(ai)
    await db_session.commit()
    ref = Reference(id=str(uuid.uuid4()), entity_type="character", entity_id=character.id,
                    role="primary", url="gen.png", asset_image_id=ai.id)
    db_session.add(ref)
    await db_session.commit()

    await client.post(f"/api/scenes/{scene.id}/links/characters/{character.id}",
                      json={"reference_id": ref.id})
    r = await client.get(f"/api/scenes/{scene.id}")
    assert r.status_code == 200
    link = r.json()["character_links"][0]
    assert link["asset_image_id"] == ai.id

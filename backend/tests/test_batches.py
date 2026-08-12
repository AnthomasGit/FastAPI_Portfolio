"""KAN-26 — batch spec expansion + POST /api/batches."""
import uuid

import pytest
from sqlalchemy import select

from database import Batch, JobRecord, Scene, Shot, Character, GeneratedImage
from services.batch_service import _resolve_targets


async def _scenes(db_session, project, n):
    scenes = []
    for i in range(n):
        s = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=i + 1,
                  slugline=f"SCENE {i+1}", screenplay="x", sort_order=i)
        db_session.add(s)
        scenes.append(s)
    await db_session.commit()
    return scenes


# ── expand: scope=project / scene → one scene_image job per scene ──────────

@pytest.mark.asyncio
async def test_project_scope_one_job_per_scene(client, db_session, project):
    await _scenes(db_session, project, 3)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_count"] == 3

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == data["batch_id"])
    )).scalars().all()
    assert len(jobs) == 3
    # scene_image jobs each created a queued GeneratedImage and link to it.
    for job in jobs:
        assert job.kind == "scene_image"
        assert job.entity_type == "generated_image"
        assert job.payload["prompt"]
        assert job.payload["generation_id"] == job.entity_id
    gens = (await db_session.execute(select(GeneratedImage))).scalars().all()
    assert len(gens) == 3


@pytest.mark.asyncio
async def test_scene_scope_targets_named_scenes(client, db_session, project):
    scenes = await _scenes(db_session, project, 4)
    picked = [scenes[0].id, scenes[2].id]
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "scene", "kind": "scene_image",
        "target_ids": picked,
    })
    assert resp.status_code == 201
    assert resp.json()["job_count"] == 2


@pytest.mark.asyncio
async def test_variants_multiply_jobs_with_distinct_seeds(client, db_session, project):
    await _scenes(db_session, project, 4)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "variants": 3,
    })
    assert resp.status_code == 201
    assert resp.json()["job_count"] == 12  # 4 scenes x 3 variants

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
    )).scalars().all()
    assert len(jobs) == 12
    assert all(j.seed is not None for j in jobs)


@pytest.mark.asyncio
async def test_shot_scope_expands_to_shots_of_scenes(db_session, project):
    """Scope resolution is tested directly: `shot` scope takes SCENE ids (despite
    the name) and expands to that scene's shots."""
    scene = (await _scenes(db_session, project, 1))[0]
    for i in range(2):
        db_session.add(Shot(id=str(uuid.uuid4()), scene_id=scene.id,
                            shot_number=f"1{chr(65+i)}", sort_order=i))
    await db_session.commit()

    targets = await _resolve_targets("shot", [scene.id], db_session)
    assert [t[0] for t in targets] == ["shot", "shot"]
    assert [t[2].shot_number for t in targets] == ["1A", "1B"]


@pytest.mark.asyncio
async def test_entity_scope_targets_entities(db_session, project):
    chars = []
    for i in range(2):
        c = Character(id=str(uuid.uuid4()), project_id=project.id, name=f"C{i}")
        db_session.add(c)
        chars.append(c)
    await db_session.commit()

    targets = await _resolve_targets("entity", [c.id for c in chars], db_session)
    assert {t[0] for t in targets} == {"character"}
    assert {t[1] for t in targets} == {c.id for c in chars}


@pytest.mark.asyncio
async def test_unmaterializable_kind_422_creates_nothing(client, db_session, project):
    """A kind with no registered materializer is refused at request time.

    Previously these fell through to a generic payload that no handler could
    consume, so the batch was accepted and every job then failed at build time
    (the KAN-51 bug). Failing here, with nothing created, is the contract.
    """
    await _scenes(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "asset_txt2img",
    })
    assert resp.status_code == 422
    assert "asset_txt2img" in resp.json()["detail"]
    assert (await db_session.execute(select(Batch))).scalars().first() is None
    assert (await db_session.execute(select(JobRecord))).scalars().first() is None


@pytest.mark.asyncio
async def test_unknown_scope_422_creates_nothing(client, db_session, project):
    await _scenes(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "galaxy", "kind": "scene_image",
    })
    assert resp.status_code == 422
    assert (await db_session.execute(select(Batch))).scalars().first() is None
    assert (await db_session.execute(select(JobRecord))).scalars().first() is None


@pytest.mark.asyncio
async def test_missing_project_404(client):
    resp = await client.post("/api/batches", json={
        "project_id": str(uuid.uuid4()), "scope": "project", "kind": "scene_image",
    })
    assert resp.status_code == 404

"""Shot-clip batch expansion (completes KAN-51).

The headline behaviour of the revamp: "Generate everything" fans out over every
SHOT in the project's master shot lists, not every scene.
"""
import os
import uuid

import pytest
from sqlalchemy import select

from database import (
    AssetImage, Batch, Character, GeneratedVideo, JobRecord, Scene, Shot,
    scene_characters,
)
import services.job_handlers as jh
from services.batch_service import _resolve_targets, target_grain, preflight


async def _scene(db_session, project, n, *, sort_order=0, slug="S"):
    scene = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=sort_order + 1,
                  slugline=f"{slug}{sort_order}", screenplay="x", sort_order=sort_order)
    db_session.add(scene)
    await db_session.flush()
    for i in range(n):
        db_session.add(Shot(id=str(uuid.uuid4()), scene_id=scene.id,
                            shot_number=f"{sort_order + 1}{chr(65 + i)}", sort_order=i))
    await db_session.commit()
    return scene


async def _character_with_image(db_session, project, scene, out_dir, name="Ada"):
    rel = f"assets/{project.id}/{name}.png"
    os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(out_dir, rel), "wb") as f:
        f.write(b"img")
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="character", status="completed", image_url=rel)
    db_session.add(asset)
    await db_session.flush()
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name=name,
                     canonical_asset_image_id=asset.id)
    db_session.add(char)
    await db_session.flush()
    await db_session.execute(scene_characters.insert().values(
        scene_id=scene.id, character_id=char.id))
    await db_session.commit()
    return char


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    return out_dir, in_dir


# ── grain ──────────────────────────────────────────────────────────────────

def test_only_shot_clip_uses_shot_grain():
    assert target_grain("shot_clip") == "shot"
    assert target_grain("scene_image") == "scene"
    assert target_grain(None) == "scene"


@pytest.mark.asyncio
async def test_project_scope_resolves_shots_in_story_order(db_session, project):
    """An overnight run should render the film front to back, so a partial
    result is still watchable in sequence."""
    await _scene(db_session, project, 2, sort_order=0)
    await _scene(db_session, project, 3, sort_order=1)

    targets = await _resolve_targets("project", [project.id], db_session, grain="shot")
    assert [t[0] for t in targets] == ["shot"] * 5
    assert [t[2].shot_number for t in targets] == ["1A", "1B", "2A", "2B", "2C"]

    # …and the same scope at scene grain still yields scenes.
    scenes = await _resolve_targets("project", [project.id], db_session, grain="scene")
    assert [t[0] for t in scenes] == ["scene", "scene"]


# ── expansion ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_everything_makes_one_job_per_shot(client, db_session, project):
    await _scene(db_session, project, 3, sort_order=0)
    await _scene(db_session, project, 2, sort_order=1)

    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["job_count"] == 5          # shots, not the 2 scenes

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == body["batch_id"])
        .order_by(JobRecord.created_at)
    )).scalars().all()
    assert {j.kind for j in jobs} == {"shot_clip"}
    # Owning rows exist up front so the Queue can show placeholders immediately.
    assert {j.entity_type for j in jobs} == {"generated_video"}
    videos = (await db_session.execute(select(GeneratedVideo))).scalars().all()
    assert len(videos) == 5
    assert all(v.status == "queued" and v.shot_id for v in videos)
    # Reference-driven clips never hang off a still.
    assert all(v.source_image_id is None for v in videos)


@pytest.mark.asyncio
async def test_payload_carries_ids_not_resolved_files(client, db_session, project):
    """Batches may run hours later, so the payload must defer resolution."""
    scene = await _scene(db_session, project, 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
    })
    job = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
    )).scalars().first()

    assert job.payload["shot_id"]
    assert job.payload["workflow_key"] == "minimax_h3_r2v"   # default
    assert job.payload["generated_video_id"]
    # No pre-resolved filenames — that is what separates this from the `video` kind.
    assert "overrides" not in job.payload
    assert "n_images" not in job.payload


@pytest.mark.asyncio
async def test_shot_audio_pick_rides_into_the_payload(client, db_session, project):
    scene = await _scene(db_session, project, 0)
    from database import ReferenceAudio
    ra = ReferenceAudio(id=str(uuid.uuid4()), audio_url="vo.wav")
    db_session.add(ra)
    db_session.add(Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A",
                        sort_order=0, reference_audio_id=ra.id))
    await db_session.commit()

    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
    })
    job = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
    )).scalars().first()
    assert job.payload["ref_audio_ids"] == [ra.id]


@pytest.mark.asyncio
async def test_variants_multiply_shots(client, db_session, project):
    await _scene(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip", "variants": 3,
    })
    assert resp.json()["job_count"] == 6
    seeds = {j.seed for j in (await db_session.execute(select(JobRecord))).scalars().all()}
    assert len(seeds) == 6      # distinct seeds, so variants actually differ


@pytest.mark.asyncio
async def test_scene_scope_limits_to_that_scenes_shots(client, db_session, project):
    a = await _scene(db_session, project, 2, sort_order=0)
    await _scene(db_session, project, 4, sort_order=1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "scene", "kind": "shot_clip",
        "target_ids": [a.id],
    })
    assert resp.json()["job_count"] == 2


# ── validation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_video_workflow_422_creates_nothing(client, db_session, project):
    await _scene(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
        "workflow": "not_a_workflow",
    })
    assert resp.status_code == 422
    assert "not_a_workflow" in resp.json()["detail"]
    assert (await db_session.execute(select(Batch))).scalars().first() is None
    assert (await db_session.execute(select(JobRecord))).scalars().first() is None


@pytest.mark.asyncio
async def test_out_of_range_setting_422(client, db_session, project):
    """Validated against VIDEO_WORKFLOWS, not the ComfyUI-graph registry — the
    two are different namespaces and using the wrong one rejects valid specs."""
    await _scene(db_session, project, 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
        "params": {"steps": 9999},
    })
    assert resp.status_code == 422
    assert (await db_session.execute(select(JobRecord))).scalars().first() is None


@pytest.mark.asyncio
async def test_valid_video_setting_accepted(client, db_session, project):
    await _scene(db_session, project, 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
        "params": {"steps": 20, "duration": 10},
    })
    assert resp.status_code == 201


# ── preflight ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preflight_flags_shots_with_no_usable_reference(db_session, project, dirs):
    """Better to learn at creation time, when the dialog can show it, than from
    a job that fails at 3am."""
    scene = await _scene(db_session, project, 2)
    spec = {"project_id": project.id, "scope": "project", "kind": "shot_clip"}

    warnings = await preflight(spec, db_session)
    assert len(warnings) == 2
    assert {w["shot_number"] for w in warnings} == {"1A", "1B"}
    assert "primary image" in warnings[0]["reason"]

    # Give the scene a character with a canonical image → warnings clear.
    await _character_with_image(db_session, project, scene, dirs[0])
    assert await preflight(spec, db_session) == []


@pytest.mark.asyncio
async def test_preflight_surfaces_in_the_create_response(client, db_session, project, dirs):
    await _scene(db_session, project, 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "shot_clip",
    })
    assert resp.status_code == 201
    assert len(resp.json()["warnings"]) == 1


@pytest.mark.asyncio
async def test_preflight_is_noop_for_other_kinds(db_session, project):
    await _scene(db_session, project, 2)
    assert await preflight(
        {"project_id": project.id, "scope": "project", "kind": "scene_image"}, db_session) == []

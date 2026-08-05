"""KAN-37 — colour-match post pass as a dependent job."""
import os
import uuid

import pytest
from sqlalchemy import select

from database import Scene, JobRecord, GeneratedImage
import services.job_handlers as jh
from services.job_handlers import build_color_match, HANDLERS
from services.job_worker import claim_jobs, resolve_parent_refs


@pytest.mark.asyncio
async def test_color_match_registered():
    assert "color_match" in HANDLERS


@pytest.mark.asyncio
async def test_build_color_match_injection(db_session, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    # Both source + reference live in the output dir.
    for rel in ("still_00001_.png", "keyframe_00001_.png"):
        with open(out_dir / rel, "wb") as f:
            f.write(b"img")

    workflow, meta = await build_color_match(
        {"source": "still_00001_.png", "reference_image": "keyframe_00001_.png",
         "job_id": "CMJOB"}, db_session)

    # Source -> node 1, reference -> node 2, both staged into the input dir.
    assert workflow["1"]["inputs"]["image"] == "CMJOB_src.png"
    assert workflow["2"]["inputs"]["image"] == "CMJOB_ref.png"
    # Film grain off (default): grain node dropped, SaveImage taps ColorMatch (3).
    assert "4" not in workflow
    assert workflow["5"]["inputs"]["images"] == ["3", 0]
    assert workflow["5"]["inputs"]["filename_prefix"] == "CMJOB"
    assert (in_dir / "CMJOB_src.png").exists()
    assert meta["image_url"] == "CMJOB_00001_.png"


@pytest.mark.asyncio
async def test_build_color_match_with_film_grain(db_session, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    for rel in ("still_00001_.png", "keyframe_00001_.png"):
        with open(out_dir / rel, "wb") as f:
            f.write(b"img")

    workflow, _meta = await build_color_match(
        {"source": "still_00001_.png", "reference_image": "keyframe_00001_.png",
         "job_id": "G", "film_grain": True, "film_grain_power": 0.6}, db_session)
    # Grain node kept; SaveImage taps it; power overridden.
    assert "4" in workflow
    assert workflow["5"]["inputs"]["images"] == ["4", 0]
    assert workflow["4"]["inputs"]["grain_power"] == 0.6


@pytest.mark.asyncio
async def test_dependent_waits_and_resolves_parent_output(client, db_session, project):
    scene = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1,
                  slugline="S", screenplay="x", sort_order=0)
    db_session.add(scene)
    await db_session.commit()

    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "color_match": True, "color_match_reference": "approved_keyframe_00001_.png",
    })
    assert resp.status_code == 201

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
        .order_by(JobRecord.created_at)
    )).scalars().all()
    kinds = sorted(j.kind for j in jobs)
    assert kinds == ["color_match", "scene_image"]
    scene_job = next(j for j in jobs if j.kind == "scene_image")
    cm_job = next(j for j in jobs if j.kind == "color_match")

    # The colour-match job depends on the still and references it via $from_parent.
    assert cm_job.depends_on_job_id == scene_job.job_id
    assert cm_job.payload["source"] == {"$from_parent": "image_url"}
    # Result is a NEW row linked to the source, not an overwrite.
    matched = await db_session.get(GeneratedImage, cm_job.payload["generation_id"])
    assert matched.kind == "color_match"
    assert matched.params["source_generation_id"] == scene_job.payload["generation_id"]
    assert matched.id != scene_job.payload["generation_id"]

    # Worker claim skips the dependent until the still completes.
    claimed = await claim_jobs(db_session, 10)
    assert scene_job.job_id in {j.job_id for j in claimed}
    assert cm_job.job_id not in {j.job_id for j in claimed}

    # Once the still completes with an output, $from_parent resolves it.
    scene_job.status = "completed"
    scene_job.image_url = "STILLJOB_00001_.png"
    await db_session.commit()
    resolved = await resolve_parent_refs(db_session, dict(cm_job.payload), scene_job.job_id)
    assert resolved["source"] == "STILLJOB_00001_.png"


@pytest.mark.asyncio
async def test_no_color_match_reference_creates_no_dependent(client, db_session, project):
    db_session.add(Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=1,
                         slugline="S", screenplay="x", sort_order=0))
    await db_session.commit()
    # color_match on but no reference -> just the still, no dependent.
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "color_match": True,
    })
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
    )).scalars().all()
    assert [j.kind for j in jobs] == ["scene_image"]

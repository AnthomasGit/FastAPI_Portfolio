"""KAN-47 — named job chains: availability, validation, expansion, isolation."""
import uuid

import pytest
from sqlalchemy import select

from database import Batch, JobRecord, Scene
import services.chains as chains
from services.chains import Chain, Stage, chain_availability, validate_chain
from services.job_worker import JobWorker


async def _scenes(db_session, project, n):
    out = []
    for i in range(n):
        s = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=i + 1,
                  slugline=f"S{i+1}", screenplay="x", sort_order=i)
        db_session.add(s)
        out.append(s)
    await db_session.commit()
    return out


@pytest.fixture
def available_chain():
    """A fully-runnable chain (scene_image → color_match, both existing kinds)
    injected for the duration of a test; the canonical chains all validate out
    today because their upscale/face-fix/dataset stages aren't exported yet."""
    name = "test_still_cm"
    chains.CHAINS[name] = Chain(
        name=name, label="Test still→cm",
        stages=(
            Stage("scene_image", label="Still"),
            Stage("color_match", parent_input="source", label="Colour match"),
        ),
    )
    try:
        yield name
    finally:
        chains.CHAINS.pop(name, None)


# ── availability + validation ────────────────────────────────────────────

def test_canonical_chains_validate_out_with_reasons():
    for name, missing_token in [
        ("still_polish", "image_upscale_refine"),
        ("still_i2v_polish", "image_face_fix"),
        ("character_kit", "dataset_export"),
    ]:
        info = chain_availability(name)
        assert info["available"] is False
        blob = " ".join(m["reason"] for m in info["missing"])
        assert missing_token in blob

def test_validate_chain_raises_naming_missing_piece():
    with pytest.raises(ValueError) as exc:
        validate_chain("still_polish")
    assert "image_upscale_refine" in str(exc.value)

def test_available_chain_validates(available_chain):
    assert validate_chain(available_chain).name == available_chain


@pytest.mark.asyncio
async def test_get_chains_endpoint(client):
    resp = await client.get("/api/chains")
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["chains"]}
    assert {"still_polish", "still_i2v_polish", "character_kit"} <= names


# ── expansion: job count + dependency links (acceptance #1) ───────────────

@pytest.mark.asyncio
async def test_chain_over_three_scenes_links_stages(client, db_session, project, available_chain):
    await _scenes(db_session, project, 3)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "chain": available_chain, "color_match_reference": "/ref.png",
    })
    assert resp.status_code == 201
    assert resp.json()["job_count"] == 6  # 2 stages × 3 scenes

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
    )).scalars().all()
    roots = [j for j in jobs if j.kind == "scene_image"]
    cms = [j for j in jobs if j.kind == "color_match"]
    assert len(roots) == 3 and len(cms) == 3
    root_ids = {r.job_id for r in roots}
    # every colour-match depends on exactly one of this batch's scene stills.
    assert all(cm.depends_on_job_id in root_ids for cm in cms)
    assert all(r.depends_on_job_id is None for r in roots)
    # $from_parent placeholder wired for the downstream input.
    assert all(cm.payload["source"] == {"$from_parent": "image_url"} for cm in cms)


# ── mid-chain failure isolates to its own tail (acceptance #2) ────────────

@pytest.mark.asyncio
async def test_midchain_failure_cancels_only_its_downstream(client, db_session, project, available_chain):
    scenes = await _scenes(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "chain": available_chain, "color_match_reference": "/ref.png",
    })
    batch_id = resp.json()["batch_id"]
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == batch_id)
    )).scalars().all()

    def cm_for(scene_id):
        root = next(j for j in jobs if j.kind == "scene_image"
                    and j.payload.get("scene_id") == scene_id)
        cm = next(j for j in jobs if j.kind == "color_match"
                  and j.depends_on_job_id == root.job_id)
        return root, cm

    root_a, cm_a = cm_for(scenes[0].id)
    root_b, cm_b = cm_for(scenes[1].id)

    # Scene A's still fails terminally → worker cascades cancel to its dependents.
    root_a.status = "failed"
    await db_session.commit()
    await JobWorker()._cancel_dependents(db_session, root_a.job_id)
    await db_session.commit()

    for j in (cm_a, cm_b, root_b):
        await db_session.refresh(j)
    assert cm_a.status == "cancelled"        # A's tail dropped
    assert cm_b.status == "queued"           # B's chain untouched
    assert root_b.status == "queued"


# ── missing-workflow chain creates nothing (acceptance #3) ────────────────

@pytest.mark.asyncio
async def test_unrunnable_chain_422_creates_nothing(client, db_session, project):
    await _scenes(db_session, project, 2)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "chain": "still_polish",
    })
    assert resp.status_code == 422
    assert "image_upscale_refine" in resp.json()["detail"]
    assert (await db_session.execute(select(Batch))).scalars().first() is None
    assert (await db_session.execute(select(JobRecord))).scalars().first() is None

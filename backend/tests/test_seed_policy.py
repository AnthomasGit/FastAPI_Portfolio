"""KAN-35 — seed policy: random | locked | derived."""
import os
import uuid

import pytest
import respx
from httpx import Response
from sqlalchemy import select

os.environ.setdefault("COMFY_API_URL", "http://test-comfyui:8188")

from services.seed_policy import resolve_seed, SEED_MAX
from services.comfyui_client import COMFY_API_URL
from database import Scene, JobRecord, GeneratedImage
from services.job_handlers import HANDLERS


# ── derived: stable across processes (hardcoded expected values) ───────────

def test_derived_is_stable_hardcoded():
    ctx = {"project_id": "proj", "target_id": "scene1", "variant_index": 0}
    # SHA-256 based — deterministic across processes (not Python's hash()).
    assert resolve_seed("derived", ctx) == 731605839403775


def test_derived_variants_are_distinct_and_stable():
    seeds = [
        resolve_seed("derived", {"project_id": "proj", "target_id": "scene1", "variant_index": v})
        for v in range(3)
    ]
    assert seeds == [731605839403775, 330310908782386, 257292937291166]
    assert len(set(seeds)) == 3  # distinct per variant
    assert all(1 <= s <= SEED_MAX for s in seeds)


# ── locked ─────────────────────────────────────────────────────────────────

def test_locked_prefers_entity_then_base_seed():
    assert resolve_seed("locked", {"locked_seed": 111, "base_seed": 222}) == 111
    assert resolve_seed("locked", {"locked_seed": None, "base_seed": 222}) == 222


def test_random_in_range():
    assert 1 <= resolve_seed("random", {}) <= SEED_MAX
    assert 1 <= resolve_seed(None, {}) <= SEED_MAX


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        resolve_seed("chaos", {})


# ── through a batch: derived seed persists + lands on the seed node ─────────

async def _scenes(db_session, project, n):
    ids = []
    for i in range(n):
        s = Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=i + 1,
                  slugline=f"S{i}", screenplay="x", sort_order=i)
        db_session.add(s)
        ids.append(s.id)
    await db_session.commit()
    return ids


@pytest.mark.asyncio
async def test_derived_batch_persists_seed_and_injects_it(client, db_session, project):
    scene_ids = await _scenes(db_session, project, 1)
    resp = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "project", "kind": "scene_image",
        "seed_policy": "derived", "variants": 2,
    })
    assert resp.status_code == 201

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == resp.json()["batch_id"])
        .order_by(JobRecord.created_at)
    )).scalars().all()
    assert len(jobs) == 2
    # Two variants of the one scene -> two distinct derived seeds.
    seeds = {j.seed for j in jobs}
    assert len(seeds) == 2

    # Seed recorded on payload AND the owning GeneratedImage row's params.
    job = jobs[0]
    assert job.payload["seed"] == job.seed
    gen = await db_session.get(GeneratedImage, job.payload["generation_id"])
    assert gen.params["seed"] == job.seed
    assert gen.params["seed_policy"] == "derived"

    # The recorded seed is what actually lands on the workflow's seed node.
    workflow, _meta = await HANDLERS["scene_image"].build_workflow(dict(job.payload), db_session)
    assert workflow["57:3"]["inputs"]["seed"] == job.seed


@pytest.mark.asyncio
async def test_derived_batch_is_reproducible(client, db_session, project):
    await _scenes(db_session, project, 2)
    body = {"project_id": project.id, "scope": "project", "kind": "scene_image",
            "seed_policy": "derived"}
    r1 = await client.post("/api/batches", json=body)
    r2 = await client.post("/api/batches", json=body)

    j1 = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r1.json()["batch_id"])
        .order_by(JobRecord.created_at))).scalars().all()
    j2 = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r2.json()["batch_id"])
        .order_by(JobRecord.created_at))).scalars().all()
    # Same project + scenes + variant indices -> identical seeds across runs.
    assert [j.seed for j in j1] == [j.seed for j in j2]

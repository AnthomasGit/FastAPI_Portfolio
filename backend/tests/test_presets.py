"""KAN-48 — saveable batch presets: CRUD, identical re-run, non-mutating overrides."""
import uuid

import pytest
from sqlalchemy import select

from database import BatchPreset, JobRecord, Scene
from services.preset_service import merge_spec


async def _scenes(db_session, project, n):
    for i in range(n):
        db_session.add(Scene(id=str(uuid.uuid4()), project_id=project.id, scene_number=i + 1,
                             slugline=f"S{i+1}", screenplay="x", sort_order=i))
    await db_session.commit()


def _spec(project_id, **over):
    return {"project_id": project_id, "scope": "project", "kind": "scene_image", **over}


async def _kinds_for(db_session, batch_id):
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == batch_id)
    )).scalars().all()
    return sorted(j.kind for j in jobs)


# ── CRUD ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preset_crud(client, project):
    spec = _spec(project.id, variants=2)
    resp = await client.post("/api/presets", json={"name": "nightly", "spec": spec,
                                                    "project_id": project.id})
    assert resp.status_code == 201
    pid = resp.json()["id"]

    assert (await client.get(f"/api/presets/{pid}")).json()["name"] == "nightly"

    upd = await client.put(f"/api/presets/{pid}", json={"name": "nightly-v2"})
    assert upd.json()["name"] == "nightly-v2"
    assert upd.json()["spec"] == spec  # spec untouched by a name-only update

    assert (await client.delete(f"/api/presets/{pid}")).status_code == 204
    assert (await client.get(f"/api/presets/{pid}")).status_code == 404


@pytest.mark.asyncio
async def test_list_includes_project_and_global(client, project):
    await client.post("/api/presets", json={"name": "mine", "spec": _spec(project.id),
                                            "project_id": project.id})
    await client.post("/api/presets", json={"name": "global", "spec": {"scope": "project",
                                            "kind": "scene_image"}})  # no project_id
    names = {p["name"] for p in (await client.get("/api/presets",
                                                  params={"project_id": project.id})).json()}
    assert {"mine", "global"} <= names


# ── run == direct spec (acceptance #1) ────────────────────────────────────

@pytest.mark.asyncio
async def test_run_matches_direct_batch(client, db_session, project):
    await _scenes(db_session, project, 3)
    spec = _spec(project.id)

    direct = await client.post("/api/batches", json=spec)
    preset = await client.post("/api/presets", json={"name": "p", "spec": spec,
                                                     "project_id": project.id})
    ran = await client.post(f"/api/presets/{preset.json()['id']}/run", json={})
    assert ran.status_code == 201

    assert ran.json()["job_count"] == direct.json()["job_count"] == 3
    assert (await _kinds_for(db_session, ran.json()["batch_id"])
            == await _kinds_for(db_session, direct.json()["batch_id"]))


# ── overrides applied, preset unchanged (acceptance #2) ───────────────────

@pytest.mark.asyncio
async def test_overrides_apply_without_mutating_preset(client, db_session, project):
    await _scenes(db_session, project, 2)
    spec = _spec(project.id, variants=1)
    pid = (await client.post("/api/presets", json={"name": "p", "spec": spec,
                                                   "project_id": project.id})).json()["id"]

    ran = await client.post(f"/api/presets/{pid}/run", json={"overrides": {"variants": 2}})
    assert ran.json()["job_count"] == 4  # 2 scenes × variants=2

    stored = (await client.get(f"/api/presets/{pid}")).json()["spec"]
    assert stored["variants"] == 1  # stored spec untouched


@pytest.mark.asyncio
async def test_global_preset_run_needs_project_via_override(client, db_session, project):
    await _scenes(db_session, project, 2)
    pid = (await client.post("/api/presets", json={"name": "g",
            "spec": {"scope": "project", "kind": "scene_image"}})).json()["id"]
    ran = await client.post(f"/api/presets/{pid}/run",
                            json={"overrides": {"project_id": project.id}})
    assert ran.status_code == 201
    assert ran.json()["job_count"] == 2


# ── merge_spec unit: nested params merge, original preserved ──────────────

def test_merge_spec_params_are_merged_not_replaced():
    spec = {"kind": "scene_image", "params": {"width": 512, "height": 512}}
    merged = merge_spec(spec, {"params": {"width": 1024}})
    assert merged["params"] == {"width": 1024, "height": 512}
    assert spec["params"] == {"width": 512, "height": 512}  # original untouched

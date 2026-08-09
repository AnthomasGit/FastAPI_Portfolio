"""Multi-angle 360 fan-out (KAN-16 follow-on): plate_angles job kind."""
import os
import uuid

import pytest

from database import AssetImage, JobRecord, Location
from services import plate_service
import services.job_handlers as jh
from services.job_handlers import build_plate_angles, on_complete_plate_angles


def _payload(project_id, src_id, *, double_ref=True, steps=20):
    return {
        "project_id": project_id,
        "source_asset_image_id": src_id,
        "front_asset_image_id": "front-asset",
        "angles": [
            {"slot": "left45", "prompt": "Rotate the camera 45 degrees to the left.", "asset_image_id": "a-left"},
            {"slot": "rear", "prompt": "Rotate the camera to the rear view.", "asset_image_id": "a-rear"},
        ],
        "double_ref": double_ref,
        "steps": steps,
        "seed": 555,
        "job_id": "JOB",
    }


@pytest.fixture
def staged_source(db_session, project, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))
    rel = "assets/p/locations/plate_00001_.png"
    os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(out_dir, rel), "wb") as f:
        f.write(b"plate")
    src = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                     entity_type="location", kind="plate", status="completed", image_url=rel)
    db_session.add(src)
    return src


@pytest.mark.asyncio
async def test_build_appends_branch_per_angle(db_session, project, staged_source):
    await db_session.commit()
    workflow, meta = await build_plate_angles(_payload(project.id, staged_source.id), db_session)

    # Front (0deg) save prefix set on the base SaveImage (node 60).
    assert workflow["60"]["inputs"]["filename_prefix"].endswith("JOB_front")
    # Two angle branches appended (8 nodes each) beyond the base's max id (60).
    saves = [n for n in workflow.values() if n["class_type"] == "SaveImage"]
    assert len(saves) == 3  # front + 2 angles
    texts = [n["inputs"]["text"] for n in workflow.values() if n["class_type"] == "CLIPTextEncode"]
    assert any("45 degrees to the left" in t for t in texts)
    assert any("rear view" in t for t in texts)

    # meta pairs each output asset with its predicted file.
    slots = {r["slot"]: r for r in meta["angle_results"]}
    assert set(slots) == {"front", "left45", "rear"}
    assert slots["front"]["asset_image_id"] == "front-asset"
    assert slots["left45"]["image_url"].endswith("JOB_left45_00001_.png")

    # Shared seed/steps across every sampler (extend + angles).
    ksamplers = [n for n in workflow.values() if n["class_type"] == "KSampler"]
    assert len(ksamplers) == 3
    assert all(k["inputs"]["seed"] == 555 and k["inputs"]["steps"] == 20 for k in ksamplers)


@pytest.mark.asyncio
async def test_double_ref_toggles_positive(db_session, project, staged_source):
    await db_session.commit()
    # double_ref ON: extend sampler reads ref#2 (node 42).
    wf_on, _ = await build_plate_angles(_payload(project.id, staged_source.id, double_ref=True), db_session)
    assert wf_on["12"]["inputs"]["positive"] == ["42", 0]
    # double_ref OFF: extend sampler falls back to ref#1 (node 41).
    wf_off, _ = await build_plate_angles(_payload(project.id, staged_source.id, double_ref=False), db_session)
    assert wf_off["12"]["inputs"]["positive"] == ["41", 0]
    # A branch KSampler's positive points at its own ref#2 (on) vs ref#1 (off).
    def _first_branch_ksampler(wf):
        ks = [(int(i), n) for i, n in wf.items() if n["class_type"] == "KSampler" and int(i) > 60]
        return min(ks)[1]
    k_on = _first_branch_ksampler(wf_on)
    k_off = _first_branch_ksampler(wf_off)
    # On → positive node id is one higher (ref#2 chained after ref#1).
    assert int(k_on["inputs"]["positive"][0]) == int(k_off["inputs"]["positive"][0]) + 1


@pytest.mark.asyncio
async def test_build_requires_source(db_session, project):
    payload = _payload(project.id, None)
    payload["source_asset_image_id"] = None
    with pytest.raises(ValueError):
        await build_plate_angles(payload, db_session)


@pytest.mark.asyncio
async def test_on_complete_finalizes_all_outputs(db_session, project):
    ids = []
    for slot in ("front", "left45", "rear"):
        a = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="queued")
        db_session.add(a)
        ids.append(a.id)
    await db_session.commit()

    results = [{"asset_image_id": i, "image_url": f"{s}.png", "slot": s}
               for i, s in zip(ids, ("front", "left45", "rear"))]
    await on_complete_plate_angles({"angle_results": results}, {}, db_session)

    for i, s in zip(ids, ("front", "left45", "rear")):
        a = await db_session.get(AssetImage, i)
        assert a.status == "completed" and a.image_url == f"{s}.png"


# ── service + endpoint ──────────────────────────────────────────────────────

async def _plated_location(db_session, project):
    plate = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed", image_url="p.png")
    db_session.add(plate)
    await db_session.flush()
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Hall",
                   plate_asset_image_id=plate.id)
    db_session.add(loc)
    await db_session.commit()
    return loc, plate


@pytest.mark.asyncio
async def test_create_plate_angles_default_set(db_session, project):
    loc, plate = await _plated_location(db_session, project)
    out = await plate_service.create_plate_angles(loc, db_session)

    # front + 3 default angles.
    assert len(out["asset_image_ids"]) == 4
    assert out["front_asset_image_id"] in out["asset_image_ids"]
    job = (await db_session.execute(
        JobRecord.__table__.select().where(JobRecord.kind == "plate_angles"))).first()
    assert {a["slot"] for a in job.payload["angles"]} == {"left45", "right45", "rear"}
    assert job.max_attempts == 1  # never auto-resubmit a multi-image render
    # Every output AssetImage links back to the source plate.
    for aid in out["asset_image_ids"]:
        a = await db_session.get(AssetImage, aid)
        assert a.source_asset_image_id == plate.id


@pytest.mark.asyncio
async def test_create_plate_angles_without_plate_raises(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bare")
    db_session.add(loc)
    await db_session.commit()
    with pytest.raises(ValueError):
        await plate_service.create_plate_angles(loc, db_session)


@pytest.mark.asyncio
async def test_angles_endpoint(client, db_session, project):
    loc, _ = await _plated_location(db_session, project)
    ok = await client.post(f"/api/locations/{loc.id}/plate/angles",
                           json={"angles": [{"slot": "left45", "prompt": "left"}], "double_ref": False})
    assert ok.status_code == 202
    assert len(ok.json()["asset_image_ids"]) == 2  # front + 1

    assert (await client.post(f"/api/locations/{uuid.uuid4()}/plate/angles", json={})).status_code == 404


@pytest.mark.asyncio
async def test_angles_endpoint_no_plate_404(client, db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bare")
    db_session.add(loc)
    await db_session.commit()
    assert (await client.post(f"/api/locations/{loc.id}/plate/angles", json={})).status_code == 404


@pytest.mark.asyncio
async def test_angles_endpoint_empty_422(client, db_session, project):
    loc, _ = await _plated_location(db_session, project)
    assert (await client.post(f"/api/locations/{loc.id}/plate/angles",
                              json={"angles": []})).status_code == 422


# ── single-angle regenerate (front-optional build) ──────────────────────────

@pytest.mark.asyncio
async def test_build_without_front_omits_front_save(db_session, project, staged_source):
    await db_session.commit()
    payload = _payload(project.id, staged_source.id)
    payload["front_asset_image_id"] = None
    payload["angles"] = [{"slot": "rear", "prompt": "rear", "asset_image_id": "a-rear"}]
    workflow, meta = await build_plate_angles(payload, db_session)

    assert "60" not in workflow  # front SaveImage removed
    slots = [r["slot"] for r in meta["angle_results"]]
    assert slots == ["rear"]  # no front result
    # The extend stage still runs (node 18 consumes node 13).
    assert "13" in workflow and "18" in workflow


@pytest.mark.asyncio
async def test_regenerate_plate_angle_reuses_row(db_session, project):
    plate = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed", image_url="p.png")
    db_session.add(plate)
    await db_session.flush()
    angle = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed",
                       image_url="old.png", source_asset_image_id=plate.id,
                       params={"angle_slot": "rear", "angle_prompt": "rear view",
                               "angle_of": plate.id, "double_ref": False, "steps": 24})
    db_session.add(angle)
    await db_session.commit()

    returned = await plate_service.regenerate_plate_angle(angle.id, db_session)
    assert returned == angle.id
    refreshed = await db_session.get(AssetImage, angle.id)
    assert refreshed.status == "queued" and refreshed.image_url is None

    job = (await db_session.execute(
        JobRecord.__table__.select().where(JobRecord.entity_id == angle.id))).first()
    assert job.kind == "plate_angles"
    assert job.payload["front_asset_image_id"] is None
    assert job.payload["angles"] == [{"slot": "rear", "prompt": "rear view", "asset_image_id": angle.id}]
    assert job.payload["double_ref"] is False and job.payload["steps"] == 24


@pytest.mark.asyncio
async def test_regenerate_missing_and_no_source_raise(db_session, project):
    with pytest.raises(ValueError):
        await plate_service.regenerate_plate_angle("nope", db_session)
    orphan = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                        entity_type="location", kind="plate", status="completed")
    db_session.add(orphan)
    await db_session.commit()
    with pytest.raises(ValueError):
        await plate_service.regenerate_plate_angle(orphan.id, db_session)


@pytest.mark.asyncio
async def test_regenerate_angle_endpoint(client, db_session, project):
    plate = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed", image_url="p.png")
    db_session.add(plate)
    await db_session.flush()
    angle = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed",
                       image_url="old.png", source_asset_image_id=plate.id,
                       params={"angle_slot": "rear", "angle_prompt": "rear", "angle_of": plate.id})
    db_session.add(angle)
    await db_session.commit()

    ok = await client.post(f"/api/asset-images/{angle.id}/regenerate-angle")
    assert ok.status_code == 202
    assert (await client.post(f"/api/asset-images/{uuid.uuid4()}/regenerate-angle")).status_code == 404

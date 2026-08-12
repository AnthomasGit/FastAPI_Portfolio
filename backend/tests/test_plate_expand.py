"""Phase 4 (KAN-43): plate expansion / outpaint job kind."""
import os
import uuid

import pytest

from database import Reference, AssetImage, JobRecord, Location
from services import plate_service
import services.job_handlers as jh
from services.job_handlers import build_plate_expand


# ── resolve_expansion ───────────────────────────────────────────────────────

def test_resolve_preset():
    assert plate_service.resolve_expansion("widen_21_9", None) == {
        "expand_left": 256, "expand_right": 256}


def test_resolve_explicit_overrides_preset():
    out = plate_service.resolve_expansion("pan_left", {"expand_left": 100, "expand_top": 64})
    assert out["expand_left"] == 100 and out["expand_top"] == 64


def test_resolve_unknown_preset_raises():
    with pytest.raises(ValueError):
        plate_service.resolve_expansion("teleport", None)


def test_resolve_empty_raises():
    with pytest.raises(ValueError):
        plate_service.resolve_expansion(None, {})


# ── build_plate_expand handler ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_lands_source_and_amounts_on_nodes(db_session, project, tmp_path, monkeypatch):
    out_dir, in_dir = tmp_path / "out", tmp_path / "in"
    out_dir.mkdir(); in_dir.mkdir()
    monkeypatch.setattr(jh, "COMFY_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(jh, "COMFY_INPUT_DIR", str(in_dir))

    # A source plate on disk.
    rel = "assets/p/locations/plate_00001_.png"
    os.makedirs(os.path.join(out_dir, os.path.dirname(rel)), exist_ok=True)
    with open(os.path.join(out_dir, rel), "wb") as f:
        f.write(b"plate")
    src = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                     entity_type="location", kind="plate", status="completed", image_url=rel)
    db_session.add(src)
    await db_session.commit()

    workflow, meta = await build_plate_expand({
        "project_id": project.id, "source_asset_image_id": src.id,
        "expand_left": 256, "expand_right": 256, "seed": 99, "job_id": "JOB",
    }, db_session)

    # Source staged onto the LoadImage node (5)...
    assert workflow["5"]["inputs"]["image"] == "JOB_source.png"
    assert os.path.exists(os.path.join(in_dir, "JOB_source.png"))
    # ...expansion amounts on the ImagePadForOutpaint node (6)...
    assert workflow["6"]["inputs"]["left"] == 256
    assert workflow["6"]["inputs"]["right"] == 256
    assert workflow["6"]["inputs"]["top"] == 0  # untouched default
    # ...seed + prefix on the sampler / save nodes.
    assert workflow["12"]["inputs"]["seed"] == 99
    assert workflow["99"]["inputs"]["filename_prefix"].endswith("JOB")
    assert meta["image_url"].endswith("JOB_00001_.png")


@pytest.mark.asyncio
async def test_build_requires_source(db_session, project):
    with pytest.raises(ValueError):
        await build_plate_expand({"project_id": project.id, "job_id": "J"}, db_session)


# ── expand_location_plate service ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_expand_links_result_to_source(db_session, project):
    plate = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed",
                       image_url="plate.png")
    db_session.add(plate)
    await db_session.flush()
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Hall")
    db_session.add(loc)
    await db_session.flush()
    db_session.add(Reference(id=str(uuid.uuid4()), entity_type="location",
                             entity_id=loc.id, role="moodboard",
                             url=plate.image_url, asset_image_id=plate.id))
    await db_session.commit()

    new_id = await plate_service.expand_location_plate(loc, db_session, preset="widen_21_9")

    new_asset = await db_session.get(AssetImage, new_id)
    assert new_asset.source_asset_image_id == plate.id  # links back to source
    assert new_asset.params["expanded_from"] == plate.id
    job = (await db_session.execute(
        JobRecord.__table__.select().where(JobRecord.entity_id == new_id))).first()
    assert job.kind == "plate_expand"
    assert job.max_attempts == 1
    assert job.payload["expand_left"] == 256 and job.payload["expand_right"] == 256


@pytest.mark.asyncio
async def test_expand_without_plate_raises(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bare")
    db_session.add(loc)
    await db_session.commit()
    with pytest.raises(ValueError):
        await plate_service.expand_location_plate(loc, db_session, preset="widen_21_9")


# ── endpoint ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expand_endpoint(client, db_session, project):
    plate = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="location", kind="plate", status="completed",
                       image_url="plate.png")
    db_session.add(plate)
    await db_session.flush()
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Hall")
    db_session.add(loc)
    await db_session.flush()
    db_session.add(Reference(id=str(uuid.uuid4()), entity_type="location",
                             entity_id=loc.id, role="moodboard",
                             url=plate.image_url, asset_image_id=plate.id))
    await db_session.commit()

    ok = await client.post(f"/api/locations/{loc.id}/plate/expand", json={"preset": "pan_left"})
    assert ok.status_code == 202
    assert ok.json()["asset_image_id"]

    # No location → 404.
    assert (await client.post(f"/api/locations/{uuid.uuid4()}/plate/expand",
                              json={"preset": "widen"})).status_code == 404
    # Bad preset → 422.
    assert (await client.post(f"/api/locations/{loc.id}/plate/expand",
                              json={"preset": "nope"})).status_code == 422


@pytest.mark.asyncio
async def test_expand_endpoint_no_plate_404(client, db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bare")
    db_session.add(loc)
    await db_session.commit()
    resp = await client.post(f"/api/locations/{loc.id}/plate/expand", json={"preset": "widen"})
    assert resp.status_code == 404

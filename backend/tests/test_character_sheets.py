"""Phase 3 (KAN-15): character sheets, contact-sheet composite, dataset export."""
import os
import io
import json
import uuid
import zipfile

import pytest
from PIL import Image

from database import AssetImage, JobRecord, Batch, Character
from services import sheet_service


def _png(path, color=(200, 100, 50), size=(64, 64)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path, "PNG")


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    d = tmp_path / "output"
    d.mkdir()
    monkeypatch.setattr(sheet_service, "COMFY_OUTPUT_DIR", str(d))
    return d


# ── 3.1 character sheet batch ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alternate_outfit_cell_drops_the_default_outfit(db_session, project):
    """An outfit cell must not name the outfit it is replacing.

    Leaving it in asserts the jersey as present fact while the suffix asks for a
    suit, and the edit model composites instead of replacing — measured: the
    jacket rendered over the jersey, on top of the track pants. Palette goes too,
    since "olive green" drags the same outfit back in by colour.
    """
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     prompt_profile={
                         "appearance": ["mid-40s man", "greying beard"],
                         "palette": ["olive green"],
                         "outfits": [
                             {"name": "matchday",
                              "items": ["olive jersey", "track pants"], "default": True},
                             {"name": "work", "items": ["charcoal suit"]},
                         ]})
    db_session.add(char)
    await db_session.commit()

    _, jobs = await sheet_service.create_character_sheet(char, db_session,
                                                         outfits=["work"])
    by_slot = {j.payload.get("sheet_slot"): j.payload["prompt"] for j in jobs
               if j.kind == "character_sheet"}

    outfit_cell = by_slot["outfit:work"]
    assert "charcoal suit" in outfit_cell
    assert "olive jersey" not in outfit_cell and "track pants" not in outfit_cell
    assert "olive green" not in outfit_cell          # palette dropped
    assert "greying beard" in outfit_cell            # identity survives

    # Angle cells keep the default outfit — that IS what the subject wears.
    assert "olive jersey" in by_slot["front"]
    assert "olive green" not in by_slot["front"]     # palette dropped everywhere

@pytest.mark.asyncio
async def test_create_sheet_fans_out_cells_with_shared_seed(db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     prompt_profile={"locked_seed": 4242, "outfits": [
                         {"name": "road", "items": ["leather jerkin"], "default": True},
                         {"name": "court", "items": ["red cloak"]},
                     ]})
    db_session.add(char)
    await db_session.commit()

    batch, jobs = await sheet_service.create_character_sheet(char, db_session,
                                                             outfits=["court"])

    cell_jobs = [j for j in jobs if j.kind == "character_sheet"]
    # 4 angles + the 1 alternate outfit that was asked for.
    assert len(cell_jobs) == 5
    assert batch.kind == "character_sheet"
    # Identical seed across every cell...
    assert {j.seed for j in cell_jobs} == {4242}
    # ...but distinct prompts (the per-cell suffix differs).
    assert len({j.payload["prompt"] for j in cell_jobs}) == 5

    assets = (await db_session.execute(
        AssetImage.__table__.select().where(AssetImage.kind == "sheet")
    )).all()
    assert len(assets) == 5
    slots = {a.params["sheet_slot"] for a in assets}
    assert "front" in slots and "outfit:court" in slots
    for a in assets:
        assert a.params["sheet_batch_id"] == batch.id
        assert a.params["character_id"] == char.id


@pytest.mark.asyncio
async def test_contact_sheet_job_depends_on_last_cell(db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()

    batch, jobs = await sheet_service.create_character_sheet(char, db_session)
    cell_jobs = [j for j in jobs if j.kind == "character_sheet"]
    contact = [j for j in jobs if j.kind == "contact_sheet"]
    assert len(contact) == 1
    assert contact[0].depends_on_job_id == cell_jobs[-1].job_id


@pytest.mark.asyncio
async def test_cells_override(db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()

    _, jobs = await sheet_service.create_character_sheet(
        char, db_session, cells=[{"slot": "solo", "suffix": "closeup"}])
    cell_jobs = [j for j in jobs if j.kind == "character_sheet"]
    assert len(cell_jobs) == 1
    assert cell_jobs[0].payload["sheet_slot"] == "solo"


@pytest.mark.asyncio
async def test_empty_cells_rejected(db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()
    with pytest.raises(ValueError):
        await sheet_service.create_character_sheet(char, db_session, cells=[])


@pytest.mark.asyncio
async def test_sheet_endpoint(client, db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()

    resp = await client.post(f"/api/characters/{char.id}/sheet")
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_count"] == 6  # base plate + 4 angle cells + contact sheet
    assert body["batch_id"]

    missing = await client.post(f"/api/characters/{uuid.uuid4()}/sheet")
    assert missing.status_code == 404


# ── 3.2 contact-sheet composite ─────────────────────────────────────────────

def test_compose_grid_dims_and_labels(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"cell{i}.png"
        _png(str(p), color=(i * 40, 100, 100))
        paths.append({"label": f"slot{i}", "path": str(p)})
    out = tmp_path / "sheet.png"
    cols, rows = sheet_service.compose_contact_sheet(paths, str(out), cell_size=64, cols=4)
    assert (cols, rows) == (4, 2)  # 5 cells -> 4 wide, 2 tall
    assert out.exists()
    img = Image.open(out)
    assert img.width == 4 * 64
    assert img.height == 2 * (64 + 22)


def test_compose_missing_cell_placeholder(tmp_path):
    cells = [
        {"label": "ok", "path": str(tmp_path / "ok.png")},
        {"label": "gone", "path": str(tmp_path / "nope.png")},  # never created
        {"label": "none", "path": None},
    ]
    _png(cells[0]["path"])
    out = tmp_path / "sheet.png"
    # Must not raise despite the missing cells.
    sheet_service.compose_contact_sheet(cells, str(out), cell_size=48, cols=3)
    assert out.exists()


@pytest.mark.asyncio
async def test_run_contact_sheet_composites_completed_cells(db_session, project, out_dir):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
    db_session.add(char)
    await db_session.commit()
    batch, _ = await sheet_service.create_character_sheet(
        char, db_session, cells=[{"slot": "a", "suffix": "x"}, {"slot": "b", "suffix": "y"}])

    # Mark the two cells completed with real image files on disk.
    cells = await sheet_service._sheet_cells(batch.id, db_session)
    for i, a in enumerate(cells):
        a.image_url = f"cell_{i}.png"
        a.status = "completed"
        _png(str(out_dir / a.image_url))
    await db_session.commit()

    contact_asset = (await db_session.execute(
        AssetImage.__table__.select().where(AssetImage.kind == "contact_sheet")
    )).first()
    meta = await sheet_service.run_contact_sheet(
        {"sheet_batch_id": batch.id, "asset_image_id": contact_asset.id,
         "project_id": project.id}, db_session)
    assert meta["image_url"]
    assert (out_dir / meta["image_url"]).exists()
    refreshed = await db_session.get(AssetImage, contact_asset.id)
    assert refreshed.status == "completed"
    assert refreshed.image_url == meta["image_url"]


# ── 3.3 dataset export ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dataset_zip_contents(db_session, project, out_dir):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero",
                     prompt_profile={"appearance": ["tall"]})
    db_session.add(char)
    await db_session.commit()
    batch, _ = await sheet_service.create_character_sheet(
        char, db_session, cells=[{"slot": "front", "suffix": "front view"},
                                 {"slot": "back", "suffix": "back view"}])
    cells = await sheet_service._sheet_cells(batch.id, db_session)
    for i, a in enumerate(cells):
        a.image_url = f"ds_{i}.png"
        a.status = "completed"
        _png(str(out_dir / a.image_url))
    await db_session.commit()

    tmp = await sheet_service.build_dataset_zip(char, db_session)
    assert tmp is not None
    try:
        with zipfile.ZipFile(tmp) as zf:
            names = zf.namelist()
            pngs = [n for n in names if n.endswith(".png")]
            txts = [n for n in names if n.endswith(".txt")]
            assert len(pngs) == 2
            assert len(txts) == 2  # one caption per image
            assert "metadata.json" in names
            # Matching basenames: image.png <-> image.txt side by side.
            assert {n[:-4] for n in pngs} == {n[:-4] for n in txts}
            meta = json.loads(zf.read("metadata.json"))
            assert meta["character_id"] == char.id
            assert meta["project_id"] == project.id
            assert len(meta["images"]) == 2
            # Caption carries the per-cell prompt.
            cap = zf.read(txts[0]).decode()
            assert "Hero" in cap
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_dataset_zip_none_when_no_sheets(db_session, project, out_dir):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Empty")
    db_session.add(char)
    await db_session.commit()
    assert await sheet_service.build_dataset_zip(char, db_session) is None


@pytest.mark.asyncio
async def test_worker_runs_contact_sheet_locally(session_factory, project, out_dir):
    """The worker completes a contact_sheet (a local job) with no ComfyUI call."""
    from services.job_worker import JobWorker

    async with session_factory() as db:
        char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Hero")
        db.add(char)
        await db.commit()
        batch, _ = await sheet_service.create_character_sheet(
            char, db, cells=[{"slot": "a", "suffix": "x"}])
        cells = await sheet_service._sheet_cells(batch.id, db)
        for i, a in enumerate(cells):
            a.image_url = f"w_{i}.png"
            a.status = "completed"
            _png(str(out_dir / a.image_url))
        contact = (await db.execute(
            AssetImage.__table__.select().where(AssetImage.kind == "contact_sheet")
        )).first()
        # Drop the dependency so the job is immediately claimable in isolation.
        cj = (await db.execute(
            JobRecord.__table__.select().where(JobRecord.kind == "contact_sheet")
        )).first()
        from sqlalchemy import update
        await db.execute(update(JobRecord).where(JobRecord.kind == "contact_sheet")
                         .values(depends_on_job_id=None))
        # Remove the cell job so only the contact_sheet is claimable.
        await db.execute(JobRecord.__table__.delete().where(
            JobRecord.kind.in_(("character_sheet", "base_plate"))))
        await db.commit()
        contact_id = contact.id
        cj_id = cj.job_id

    worker = JobWorker(session_factory=session_factory, max_inflight=1)
    processed = await worker.tick()
    assert processed == 1
    async with session_factory() as db:
        job = await db.get(JobRecord, cj_id)
        assert job.status == "completed"
        asset = await db.get(AssetImage, contact_id)
        assert asset.status == "completed" and asset.image_url


@pytest.mark.asyncio
async def test_dataset_endpoint_404_without_sheets(client, db_session, project):
    char = Character(id=str(uuid.uuid4()), project_id=project.id, name="Empty")
    db_session.add(char)
    await db_session.commit()
    resp = await client.get(f"/api/characters/{char.id}/dataset.zip")
    assert resp.status_code == 404

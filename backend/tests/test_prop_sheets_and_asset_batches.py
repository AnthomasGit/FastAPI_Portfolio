"""Prop sheets + per-tab asset batches (Characters / Props / Locations).

These are the batches the storyboard tabs' Generate buttons submit. The property
that matters most: they materialize into the CALLER's batch and transaction —
the standalone endpoints create their own batch and commit, and doing that
inside create_batch would persist a half-built one.
"""
import uuid

import pytest
from sqlalchemy import select

from database import AssetImage, Batch, Character, JobRecord, Location, Prop, Reference
from services.sheet_service import (
    SHEET_TEMPLATES, PROP_ANGLE_CELLS, ANGLE_CELLS, default_cells,
)
from services.prompt_builder import entity_prompt


async def _prop(db_session, project, name="Knife", profile=None):
    p = Prop(id=str(uuid.uuid4()), project_id=project.id, name=name,
             prompt_profile=profile)
    db_session.add(p)
    await db_session.commit()
    return p


async def _location(db_session, project, name="Bar"):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name=name)
    db_session.add(loc)
    await db_session.commit()
    return loc


# ── templates ──────────────────────────────────────────────────────────────

def test_props_are_front_three_quarter_and_detail_only():
    """No full turntable. `side`/`back`/`top` were measured against live ComfyUI
    and all three came back as the front face again — a prop's appearance tokens
    describe one face, so a cell that turns away contradicts its own base line.
    Near-duplicates are worse than absent when these fill R2V reference slots."""
    slots = {c["slot"] for c in default_cells(Prop(id="p", name="Knife"), "prop")}
    assert slots == {"front", "three-quarter", "detail"}


def test_characters_are_angles_plus_alternate_outfits():
    """Expression cells were dropped: they gave the edit model nothing to act on
    (a head-and-shoulders noun phrase against a full-body source), and a sheet's
    job is angle + wardrobe coverage for reference slots, not acting range.

    Only ALTERNATE outfits get a cell — the default one is already worn in every
    angle cell, so a cell for it would render the same clothes twice."""
    char = Character(id="c", name="Ada", prompt_profile={"outfits": [
        {"name": "day", "items": ["red coat"], "default": True},
        {"name": "gala", "items": ["black gown", "silver heels"]},
    ]})
    slots = {c["slot"] for c in default_cells(char, "character")}
    assert not any(s.startswith("expr-") for s in slots)
    assert "outfit:gala" in slots
    assert "outfit:day" not in slots

    suffix = next(c["suffix"] for c in default_cells(char, "character")
                  if c["slot"] == "outfit:gala")
    assert "black gown, silver heels" in suffix   # the whole set, worn together


def test_legacy_wardrobe_list_reads_as_one_default_outfit():
    """Un-migrated profiles keep composing the same base line, and stop emitting
    a redundant cell per garment."""
    char = Character(id="c", name="Ada",
                     prompt_profile={"wardrobe": ["red coat", "boots"]})
    assert entity_prompt(char) == "Ada: red coat, boots"
    assert [c["slot"] for c in default_cells(char, "character")] == \
           [c["slot"] for c in ANGLE_CELLS]


def test_props_vary_over_materials():
    """Each type varies over its own profile list — wardrobe for a character,
    materials for a prop."""
    prop = Prop(id="p", name="Knife", prompt_profile={"materials": ["brass"]})
    cells = default_cells(prop, "prop")
    assert any(c["slot"] == "materials:brass" for c in cells)
    assert SHEET_TEMPLATES["prop"]["variant_prefix"] == "materials"


def test_unknown_entity_type_rejected():
    with pytest.raises(ValueError, match="No sheet template"):
        default_cells(Location(id="l", name="Bar"), "location")


# ── standalone prop sheet endpoint ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_prop_sheet_endpoint_creates_cells_and_composite(client, db_session, project):
    prop = await _prop(db_session, project)
    r = await client.post(f"/api/props/{prop.id}/sheet")
    assert r.status_code == 202
    assert r.json()["job_count"] == len(PROP_ANGLE_CELLS) + 1     # cells + contact sheet

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r.json()["batch_id"])
    )).scalars().all()
    kinds = [j.kind for j in jobs]
    assert kinds.count("prop_sheet") == len(PROP_ANGLE_CELLS)
    assert kinds.count("contact_sheet") == 1
    # Every cell shares one seed, which is what makes a sheet one object.
    assert len({j.seed for j in jobs if j.kind == "prop_sheet"}) == 1


@pytest.mark.asyncio
async def test_prop_sheet_404(client):
    assert (await client.post(f"/api/props/{uuid.uuid4()}/sheet")).status_code == 404


@pytest.mark.asyncio
async def test_prop_sheet_assets_tagged_for_the_prop(client, db_session, project):
    prop = await _prop(db_session, project)
    await client.post(f"/api/props/{prop.id}/sheet")
    assets = (await db_session.execute(
        select(AssetImage).where(AssetImage.entity_type == "prop")
    )).scalars().all()
    assert assets and all((a.params or {}).get("prop_id") == prop.id for a in assets)


# ── the from_canonical / workflow routing gotcha ───────────────────────────

@pytest.mark.asyncio
async def test_from_canonical_false_clears_source_so_workflow_applies(
        client, db_session, project):
    """build_sheet_cell only honours `workflow` on the txt2img branch — with a
    canonical image present, img2img wins. So "render fresh with krea2" has to
    clear the source, or the model choice would silently do nothing.
    """
    asset = AssetImage(id=str(uuid.uuid4()), origin_project_id=project.id,
                       entity_type="prop", status="completed", image_url="x.png")
    db_session.add(asset)
    await db_session.flush()
    prop = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Knife")
    db_session.add(prop)
    await db_session.flush()
    # The sheet's base image is the entity's newest generated reference.
    db_session.add(Reference(id=str(uuid.uuid4()), entity_type="prop",
                             entity_id=prop.id, role="moodboard",
                             url="x.png", asset_image_id=asset.id))
    await db_session.commit()

    r = await client.post(f"/api/props/{prop.id}/sheet",
                          json={"from_canonical": False, "workflow": "krea2_turbo"})
    job = (await db_session.execute(
        select(JobRecord).where(JobRecord.kind == "prop_sheet")
    )).scalars().first()
    assert job.payload["source_asset_image_id"] is None
    assert job.payload["workflow"] == "krea2_turbo"

    # …and the default keeps img2img off the canonical image.
    r2 = await client.post(f"/api/props/{prop.id}/sheet")
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r2.json()["batch_id"],
                                JobRecord.kind == "prop_sheet")
    )).scalars().all()
    assert all(j.payload["source_asset_image_id"] == asset.id for j in jobs)


# ── per-tab entity batches ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_props_tab_batch_makes_one_sheet_per_prop(client, db_session, project):
    props = [await _prop(db_session, project, f"P{i}") for i in range(2)]
    r = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "entity", "kind": "prop_sheet",
        "target_ids": [p.id for p in props],
    })
    assert r.status_code == 201
    # 2 props × (6 cells + 1 composite)
    assert r.json()["job_count"] == 2 * (len(PROP_ANGLE_CELLS) + 1)

    # Exactly ONE batch: the sheet service must not create its own here.
    assert len((await db_session.execute(select(Batch))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_characters_tab_batch_still_works(client, db_session, project):
    chars = [Character(id=str(uuid.uuid4()), project_id=project.id, name=f"C{i}")
             for i in range(2)]
    for c in chars:
        db_session.add(c)
    await db_session.commit()
    r = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "entity", "kind": "character_sheet",
        "target_ids": [c.id for c in chars],
    })
    assert r.status_code == 201
    assert len((await db_session.execute(select(Batch))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_locations_tab_batch_chains_plate_then_angles(client, db_session, project):
    """The angles job needs Location.plate_asset_image_id, which only the plate
    job's on_complete sets — so it depends on the plate rather than reading it."""
    loc = await _location(db_session, project)
    r = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "entity", "kind": "location_plate",
        "target_ids": [loc.id], "with_angles": True,
    })
    assert r.status_code == 201

    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r.json()["batch_id"])
    )).scalars().all()
    plate = next(j for j in jobs if j.kind == "location_plate")
    angles = next(j for j in jobs if j.kind == "plate_angles")
    assert angles.depends_on_job_id == plate.job_id
    # Source is unknown at expansion time; the builder re-reads it via location_id.
    assert angles.payload["source_asset_image_id"] is None
    assert angles.payload["location_id"] == loc.id


@pytest.mark.asyncio
async def test_location_batch_defaults_to_wide_plate_without_angles(
        client, db_session, project):
    loc = await _location(db_session, project)
    r = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "entity", "kind": "location_plate",
        "target_ids": [loc.id],
    })
    jobs = (await db_session.execute(
        select(JobRecord).where(JobRecord.batch_id == r.json()["batch_id"])
    )).scalars().all()
    assert [j.kind for j in jobs] == ["location_plate"]
    # z-image turbo at 16:9 is already the default — nothing to override.
    assert jobs[0].payload["width"] > jobs[0].payload["height"]


@pytest.mark.asyncio
async def test_entity_batch_skips_targets_of_other_types(client, db_session, project):
    """An entity-scope batch resolves all three types; a sheet materializer must
    ignore the ones it doesn't handle rather than erroring."""
    prop = await _prop(db_session, project)
    loc = await _location(db_session, project)
    r = await client.post("/api/batches", json={
        "project_id": project.id, "scope": "entity", "kind": "prop_sheet",
        "target_ids": [prop.id, loc.id],
    })
    assert r.status_code == 201
    assert r.json()["job_count"] == len(PROP_ANGLE_CELLS) + 1   # prop only

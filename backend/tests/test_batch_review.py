"""Batch review and commit.

The two invariants worth protecting:
  * commit is idempotent (references dedupe, approvals only set once), and
  * committing only creates the pool Reference — there is no global canonical
    to overwrite, so a scene that has picked keeps its choice untouched.
"""
import uuid

import pytest
from sqlalchemy import select

from database import (
    AssetImage, Batch, Character, GeneratedVideo, JobRecord, Location, Prop,
    Reference, Scene, Shot,
)
from services.batch_results_service import commit_batch, list_artifacts


async def _batch(db_session, project, kind="prop_sheet", status="pending"):
    b = Batch(id=str(uuid.uuid4()), project_id=project.id, kind=kind, status=status)
    db_session.add(b)
    await db_session.flush()
    return b


async def _sheet_artifact(db_session, project, batch, entity, entity_type,
                          *, status="completed", kind="sheet", slot="front"):
    asset = AssetImage(
        id=str(uuid.uuid4()), origin_project_id=project.id, entity_type=entity_type,
        kind=kind, status=status, image_url=f"a/{uuid.uuid4()}.png",
        params={"sheet_slot": slot, "sheet_batch_id": batch.id,
                "entity_type": entity_type, "entity_id": entity.id,
                f"{entity_type}_id": entity.id},
    )
    db_session.add(asset)
    await db_session.flush()
    db_session.add(JobRecord(
        kind=f"{entity_type}_sheet", status="completed", batch_id=batch.id,
        entity_type="asset_image", entity_id=asset.id, payload={},
    ))
    await db_session.flush()
    return asset


async def _clip_artifact(db_session, project, batch, scene, *, status="completed"):
    shot = Shot(id=str(uuid.uuid4()), scene_id=scene.id, shot_number="1A")
    db_session.add(shot)
    await db_session.flush()
    video = GeneratedVideo(id=str(uuid.uuid4()), project_id=project.id,
                           scene_id=scene.id, shot_id=shot.id, status=status,
                           video_url=f"v/{uuid.uuid4()}.mp4")
    db_session.add(video)
    await db_session.flush()
    db_session.add(JobRecord(
        kind="shot_clip", status="completed", batch_id=batch.id,
        entity_type="generated_video", entity_id=video.id, payload={},
    ))
    await db_session.flush()
    return video


async def _prop(db_session, project, **kw):
    p = Prop(id=str(uuid.uuid4()), project_id=project.id, name="Knife", **kw)
    db_session.add(p)
    await db_session.flush()
    return p


# ── enumeration ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_artifacts_carry_type_url_and_target(db_session, project, scene):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop")
    await _clip_artifact(db_session, project, batch, scene)
    await db_session.commit()

    items = await list_artifacts(batch.id, db_session)
    assert {i["artifact_type"] for i in items} == {"asset_image", "generated_video"}
    img = next(i for i in items if i["artifact_type"] == "asset_image")
    assert img["target"] == {"type": "prop", "id": prop.id, "name": "Knife"}
    assert img["url"].endswith("/file")
    assert img["slot"] == "front"
    clip = next(i for i in items if i["artifact_type"] == "generated_video")
    assert clip["target"]["type"] == "shot" and clip["target"]["name"] == "1A"


@pytest.mark.asyncio
async def test_incomplete_artifacts_hidden_unless_asked(db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop", status="failed")
    await db_session.commit()

    assert await list_artifacts(batch.id, db_session) == []
    assert len(await list_artifacts(batch.id, db_session, include_failed=True)) == 1


@pytest.mark.asyncio
async def test_deleted_artifact_disappears_from_the_grid(db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    asset = await _sheet_artifact(db_session, project, batch, prop, "prop")
    await db_session.commit()
    assert len(await list_artifacts(batch.id, db_session)) == 1

    await db_session.delete(asset)
    await db_session.commit()
    assert await list_artifacts(batch.id, db_session) == []


# ── commit ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commit_links_the_reference(db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    asset = await _sheet_artifact(db_session, project, batch, prop, "prop")
    await db_session.commit()

    counts = await commit_batch(batch, db_session)
    assert counts["references_created"] == 1

    # Creating the Reference IS the commit: a scene with no explicit pick
    # inherits the entity's newest reference, so this is immediately usable.
    refs = (await db_session.execute(select(Reference).where(
        Reference.entity_id == prop.id))).scalars().all()
    assert len(refs) == 1 and refs[0].asset_image_id == asset.id
    assert batch.committed_at is not None


@pytest.mark.asyncio
async def test_commit_leaves_an_explicit_scene_pick_alone(db_session, project, scene):
    """A deliberate per-scene choice must survive a later batch."""
    from database import scene_props
    prop = await _prop(db_session, project)
    chosen = Reference(id=str(uuid.uuid4()), entity_type="prop", entity_id=prop.id,
                       role="moodboard", url="chosen.png")
    db_session.add(chosen)
    await db_session.flush()
    await db_session.execute(scene_props.insert().values(
        scene_id=scene.id, prop_id=prop.id, reference_id=chosen.id))
    batch = await _batch(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop")
    await db_session.commit()

    counts = await commit_batch(batch, db_session)
    assert counts["references_created"] == 1        # added to the pool…

    from services.job_handlers import scene_primary_reference
    still = await scene_primary_reference(scene.id, "prop", prop.id, db_session)
    assert still.id == chosen.id                    # …but the scene keeps its pick


@pytest.mark.asyncio
async def test_commit_is_idempotent(db_session, project, scene):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop")
    await _clip_artifact(db_session, project, batch, scene)
    await db_session.commit()

    first = await commit_batch(batch, db_session)
    assert first["references_created"] == 1 and first["clips_approved"] == 1

    second = await commit_batch(batch, db_session)
    assert second == {"references_created": 0, "clips_approved": 0, "skipped": 0}
    refs = (await db_session.execute(select(Reference))).scalars().all()
    assert len(refs) == 1          # no duplicate pool row


@pytest.mark.asyncio
async def test_location_plate_artifact_becomes_a_reference(db_session, project):
    loc = Location(id=str(uuid.uuid4()), project_id=project.id, name="Bar")
    db_session.add(loc)
    await db_session.flush()
    batch = await _batch(db_session, project, kind="location_plate")
    asset = await _sheet_artifact(db_session, project, batch, loc, "location", kind="plate")
    await db_session.commit()

    counts = await commit_batch(batch, db_session)
    assert counts["references_created"] == 1
    refs = (await db_session.execute(select(Reference).where(
        Reference.entity_id == loc.id))).scalars().all()
    assert [r.asset_image_id for r in refs] == [asset.id]


@pytest.mark.asyncio
async def test_clips_get_approved_at(db_session, project, scene):
    batch = await _batch(db_session, project, kind="shot_clip")
    video = await _clip_artifact(db_session, project, batch, scene)
    await db_session.commit()

    await commit_batch(batch, db_session)
    await db_session.refresh(video)
    assert video.approved_at is not None


@pytest.mark.asyncio
async def test_rejected_artifact_is_not_committed(db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    keep = await _sheet_artifact(db_session, project, batch, prop, "prop", slot="front")
    drop = await _sheet_artifact(db_session, project, batch, prop, "prop", slot="side")
    await db_session.commit()

    await db_session.delete(drop)          # the user rejected it during review
    await db_session.commit()

    counts = await commit_batch(batch, db_session)
    assert counts["references_created"] == 1
    refs = (await db_session.execute(select(Reference))).scalars().all()
    assert [r.asset_image_id for r in refs] == [keep.id]


# ── endpoints ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commit_409_while_batch_still_running(client, db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop")
    # A queued job makes the batch non-terminal.
    db_session.add(JobRecord(kind="prop_sheet", status="queued", batch_id=batch.id,
                             entity_type="asset_image", entity_id=str(uuid.uuid4()),
                             payload={}))
    await db_session.commit()

    r = await client.post(f"/api/batches/{batch.id}/commit")
    assert r.status_code == 409
    await db_session.refresh(batch)
    assert batch.committed_at is None       # nothing half-approved


@pytest.mark.asyncio
async def test_artifacts_and_commit_endpoints(client, db_session, project):
    batch = await _batch(db_session, project)
    prop = await _prop(db_session, project)
    await _sheet_artifact(db_session, project, batch, prop, "prop")
    await db_session.commit()

    r = await client.get(f"/api/batches/{batch.id}/artifacts")
    assert r.status_code == 200 and len(r.json()["artifacts"]) == 1

    r = await client.post(f"/api/batches/{batch.id}/commit")
    assert r.status_code == 200 and r.json()["references_created"] == 1


@pytest.mark.asyncio
async def test_artifacts_404_for_unknown_batch(client):
    assert (await client.get(f"/api/batches/{uuid.uuid4()}/artifacts")).status_code == 404


@pytest.mark.asyncio
async def test_delete_video_endpoint(client, db_session, project, scene):
    batch = await _batch(db_session, project)
    video = await _clip_artifact(db_session, project, batch, scene)
    await db_session.commit()

    assert (await client.delete(f"/api/generate/video/{video.id}")).status_code == 204
    assert (await db_session.execute(
        select(GeneratedVideo).where(GeneratedVideo.id == video.id))).scalars().first() is None
    assert (await client.delete(f"/api/generate/video/{uuid.uuid4()}")).status_code == 404

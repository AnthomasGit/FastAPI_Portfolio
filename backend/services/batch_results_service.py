"""Batch review and commit.

A finished batch is not the end of the workflow — it is a pile of candidates.
The Queue shows everything a batch produced, the user deletes the misses, and
"Save all" commits the survivors: each image is linked to its entity as a pool
Reference, and becomes that entity's canonical/plate **only if one isn't already
chosen**. Clips are marked approved.

Two rules make this safe to re-run:
  * References are deduped by asset_image_id (assign_asset_to_entity), and
  * canonical/plate are set only when unset — never overwritten.
A deliberate pick must survive a later batch, because a silently re-canonicalised
character is invisible until a whole render comes back wrong.
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    AssetImage, Batch, Character, GeneratedImage, GeneratedVideo, JobRecord,
    Location, Prop, Scene, Shot,
)
from services.reference_service import assign_asset_to_entity

logger = logging.getLogger(__name__)

ENTITY_MODELS = {"character": Character, "location": Location, "prop": Prop}
# Job entity_type -> the artifact table it owns.
_ARTIFACT_MODELS = {
    "asset_image": AssetImage,
    "generated_image": GeneratedImage,
    "generated_video": GeneratedVideo,
}
TERMINAL_BATCH_STATES = ("completed", "failed", "cancelled")


def _target_of(artifact, artifact_type: str) -> tuple[str | None, str | None]:
    """(entity_type, entity_id) an artifact belongs to, or (None, None).

    Sheet/plate services already stamp the owning entity onto params, so this
    reads what they wrote rather than re-deriving it from the job graph.
    """
    if artifact_type == "asset_image":
        params = artifact.params or {}
        etype = params.get("entity_type") or artifact.entity_type
        eid = params.get("entity_id") or (params.get(f"{etype}_id") if etype else None)
        return (etype, eid) if etype and eid else (None, None)
    return (None, None)


async def list_artifacts(batch_id: str, db: AsyncSession,
                         include_failed: bool = False) -> list[dict]:
    """Everything a batch produced, ready for the review grid."""
    jobs = (await db.execute(
        select(JobRecord).where(JobRecord.batch_id == batch_id)
        .order_by(JobRecord.created_at.asc())
    )).scalars().all()

    # Group ids per table so each is one query, not one per job.
    by_type: dict[str, list[str]] = {}
    for job in jobs:
        if job.entity_type in _ARTIFACT_MODELS and job.entity_id:
            by_type.setdefault(job.entity_type, []).append(job.entity_id)

    loaded: dict[tuple[str, str], object] = {}
    for atype, ids in by_type.items():
        model = _ARTIFACT_MODELS[atype]
        rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
        for row in rows:
            loaded[(atype, row.id)] = row

    # Resolve target names in bulk too.
    names: dict[tuple[str, str], str] = {}
    wanted: dict[str, set[str]] = {}
    for job in jobs:
        art = loaded.get((job.entity_type, job.entity_id))
        if art is None:
            continue
        etype, eid = _target_of(art, job.entity_type)
        if etype and eid:
            wanted.setdefault(etype, set()).add(eid)
    for etype, ids in wanted.items():
        model = ENTITY_MODELS.get(etype)
        if model is None:
            continue
        rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
        for row in rows:
            names[(etype, row.id)] = row.name

    shot_numbers: dict[str, str] = {}
    shot_ids = [a.shot_id for (t, _), a in loaded.items()
                if t == "generated_video" and getattr(a, "shot_id", None)]
    if shot_ids:
        rows = (await db.execute(select(Shot).where(Shot.id.in_(shot_ids)))).scalars().all()
        shot_numbers = {s.id: s.shot_number or "" for s in rows}

    out: list[dict] = []
    for job in jobs:
        art = loaded.get((job.entity_type, job.entity_id))
        if art is None:
            continue  # the artifact was deleted during review
        status = getattr(art, "status", None)
        if not include_failed and status != "completed":
            continue

        atype = job.entity_type
        if atype == "generated_video":
            url = f"/api/generate/video/file/{art.id}" if art.video_url else None
            target = {"type": "shot", "id": art.shot_id,
                      "name": shot_numbers.get(art.shot_id or "", "")}
            committed = art.approved_at is not None
        elif atype == "generated_image":
            url = f"/api/generate/image/{art.id}" if art.image_url else None
            target = {"type": "scene", "id": art.scene_id, "name": ""}
            committed = False
        else:
            url = f"/api/asset-images/{art.id}/file" if art.image_url else None
            etype, eid = _target_of(art, atype)
            target = {"type": etype, "id": eid, "name": names.get((etype, eid), "")}
            committed = False

        out.append({
            "artifact_type": atype,
            "id": art.id,
            "job_id": job.job_id,
            "job_kind": job.kind,
            "status": status,
            "url": url,
            "prompt": getattr(art, "prompt", None),
            "slot": (getattr(art, "params", None) or {}).get("sheet_slot")
                    or (getattr(art, "params", None) or {}).get("angle_slot"),
            "target": target,
            "committed": committed,
            "error": getattr(art, "error", None),
        })
    return out


async def commit_batch(batch: Batch, db: AsyncSession) -> dict:
    """Save a reviewed batch's survivors. Idempotent."""
    artifacts = await list_artifacts(batch.id, db)
    counts = {"references_created": 0, "clips_approved": 0, "skipped": 0}
    now = datetime.utcnow()

    for item in artifacts:
        if item["artifact_type"] == "generated_video":
            video = await db.get(GeneratedVideo, item["id"])
            if video is not None and video.approved_at is None:
                video.approved_at = now
                counts["clips_approved"] += 1
            continue

        if item["artifact_type"] != "asset_image":
            counts["skipped"] += 1
            continue

        etype, eid = item["target"]["type"], item["target"]["id"]
        model = ENTITY_MODELS.get(etype or "")
        if model is None or not eid:
            counts["skipped"] += 1
            continue
        entity = await db.get(model, eid)
        asset = await db.get(AssetImage, item["id"])
        if entity is None or asset is None:
            counts["skipped"] += 1
            continue

        _ref, created = await assign_asset_to_entity(db, etype, eid, asset)
        if created:
            counts["references_created"] += 1

        # Nothing else to set: there is no global canonical any more. Creating
        # the Reference IS the commit — a scene with no explicit pick inherits
        # the entity's newest reference, so a committed image is immediately
        # usable, and a scene that HAS picked keeps its choice untouched.

    batch.committed_at = batch.committed_at or now
    await db.commit()
    return counts

"""Master shot list CRUD + AI draft.

A Shot's metadata (size/angle/movement/audio) composes into the LTX motion
prompt downstream, so this is planning data with teeth, not just notes.
Mirrors scene_link_service/staging_service conventions.
"""

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import Shot, Scene, GeneratedImage
from schemas.schemas import (
    ShotResponse, ShotCreate, ShotUpdate, GenerateImageResponse,
)
from services import ai_service


# generated_image (and its .videos) eager-loaded so ShotResponse.still can carry
# the clip without a second round-trip; .videos is already lazy="selectin".
_SHOT_OPTS = [selectinload(Shot.generated_image).selectinload(GeneratedImage.videos)]


def _to_response(shot: Shot) -> ShotResponse:
    resp = ShotResponse.model_validate(shot)
    resp.still = (
        GenerateImageResponse.model_validate(shot.generated_image)
        if shot.generated_image
        else None
    )
    return resp


async def list_shots(db: AsyncSession, scene_id: str) -> list[ShotResponse]:
    result = await db.execute(
        select(Shot).options(*_SHOT_OPTS)
        .where(Shot.scene_id == scene_id)
        .order_by(Shot.sort_order)
    )
    return [_to_response(s) for s in result.scalars().all()]


async def _load(db: AsyncSession, shot_id: str) -> Shot | None:
    # populate_existing forces selectinload to refresh an instance already in
    # the identity map — otherwise a just-set generated_image_id can come back
    # with its relationship unloaded (still=None) on a mutation's own response.
    result = await db.execute(
        select(Shot).options(*_SHOT_OPTS)
        .where(Shot.id == shot_id)
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


async def create_shot(db: AsyncSession, scene_id: str, data: ShotCreate) -> ShotResponse:
    # Append to the end unless a sort_order was supplied.
    sort_order = data.sort_order
    if not sort_order:
        existing = await db.execute(
            select(Shot.sort_order).where(Shot.scene_id == scene_id)
        )
        orders = [o for (o,) in existing.all() if o is not None]
        sort_order = (max(orders) + 1) if orders else 0

    shot = Shot(
        scene_id=scene_id,
        shot_number=data.shot_number,
        sort_order=sort_order,
        shot_size=data.shot_size,
        angle=data.angle,
        movement=data.movement,
        description=data.description,
        equipment=data.equipment,
        audio_notes=data.audio_notes,
        capture_id=data.capture_id,
        generated_image_id=data.generated_image_id,
    )
    db.add(shot)
    await db.commit()
    return await _reload_response(db, shot.id)


async def update_shot(db: AsyncSession, shot_id: str, data: ShotUpdate) -> ShotResponse | None:
    shot = await _load(db, shot_id)
    if not shot:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(shot, field, value)
    await db.commit()
    return await _reload_response(db, shot_id)


async def delete_shot(db: AsyncSession, shot_id: str) -> bool:
    shot = await db.get(Shot, shot_id)
    if not shot:
        return False
    await db.delete(shot)
    await db.commit()
    return True


async def reorder_shots(db: AsyncSession, scene_id: str, shot_ids: list[str]) -> list[ShotResponse]:
    for index, sid in enumerate(shot_ids):
        shot = await db.get(Shot, sid)
        if shot and shot.scene_id == scene_id:
            shot.sort_order = index
    await db.commit()
    return await list_shots(db, scene_id)


async def generate_shot_list(db: AsyncSession, scene: Scene) -> list[ShotResponse]:
    """AI-draft coverage for a scene, appended after any existing shots."""
    drafts = await ai_service.generate_shot_list(scene.slugline or "", scene.screenplay or "")

    existing = await db.execute(select(Shot.sort_order).where(Shot.scene_id == scene.id))
    orders = [o for (o,) in existing.all() if o is not None]
    next_order = (max(orders) + 1) if orders else 0

    for i, d in enumerate(drafts):
        db.add(Shot(
            scene_id=scene.id,
            shot_number=d.get("shot_number"),
            sort_order=next_order + i,
            shot_size=d.get("shot_size"),
            angle=d.get("angle"),
            movement=d.get("movement"),
            description=d.get("description"),
            equipment=d.get("equipment"),
            audio_notes=d.get("audio_notes"),
        ))
    await db.commit()
    return await list_shots(db, scene.id)


async def _reload_response(db: AsyncSession, shot_id: str) -> ShotResponse:
    shot = await _load(db, shot_id)
    return _to_response(shot)

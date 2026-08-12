from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Reference


async def assign_asset_to_entity(db: AsyncSession, entity_type: str, entity_id: str,
                                 asset) -> tuple[Reference, bool]:
    """Find-or-create the pool Reference linking an AssetImage to an entity.

    Returns (reference, created). Deduped by asset_image_id so re-assigning the
    same generated image doesn't pile up duplicate pool rows — which is also
    what makes batch commit idempotent. `entity_type` is SINGULAR.

    Does not commit: the caller owns the transaction (the assign endpoint
    commits per call; batch commit commits once for the whole batch).
    """
    existing = await db.execute(
        select(Reference).where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
            Reference.asset_image_id == asset.id,
        )
    )
    ref = existing.scalars().first()
    if ref:
        ref.url = asset.image_url
        return ref, False
    ref = Reference(
        entity_type=entity_type,
        entity_id=entity_id,
        role="moodboard",
        url=asset.image_url,
        asset_image_id=asset.id,
    )
    db.add(ref)
    return ref, True


async def delete_entity_references(db: AsyncSession, entity_type: str, entity_id: str) -> None:
    await db.execute(
        delete(Reference).where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
        )
    )


async def newest_reference_id(db: AsyncSession, entity_type: str, entity_id: str) -> str | None:
    """The asset's most recently added reference, used as the default primary
    for a scene that hasn't picked one yet. There is no global/canonical
    primary — every scene either inherits this default or overrides it via
    scene_X.reference_id.
    """
    result = await db.execute(
        select(Reference.id)
        .where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
        )
        .order_by(Reference.created_at.desc())
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def get_entity(db: AsyncSession, entity_type: str, entity_id: str):
    from database import Scene, Character, Location, Prop
    tables = {
        "scene": Scene,
        "character": Character,
        "location": Location,
        "prop": Prop,
    }
    table = tables.get(entity_type)
    if table is None:
        return None
    result = await db.execute(select(table).where(table.id == entity_id))
    return result.scalars().first()

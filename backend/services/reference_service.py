from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import Reference


async def delete_entity_references(db: AsyncSession, entity_type: str, entity_id: str) -> None:
    await db.execute(
        delete(Reference).where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
        )
    )


async def enforce_single_primary(
    db: AsyncSession, entity_type: str, entity_id: str, keep_ref_id: str
) -> None:
    """Demote every other role='primary' reference for this entity to 'moodboard'.

    Primary is the entity's single canonical/default reference (the per-scene
    source of truth is scene_X.reference_id, a separate one-per-scene concept).
    Callers must commit; this only stages the update.
    """
    await db.execute(
        update(Reference)
        .where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
            Reference.role == "primary",
            Reference.id != keep_ref_id,
        )
        .values(role="moodboard")
    )


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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    scene_characters, scene_locations, scene_props,
    Character, Location, Prop, Reference, Scene,
)
from schemas.schemas import SceneEntityLink, SceneResponse


class LinkNotFound(Exception):
    """Scene, entity, or link row does not exist -> 404."""


class LinkInvalid(Exception):
    """Cross-project link or reference not owned by the entity -> 422."""


# plural entity_type -> association table, its entity id column, ORM model,
# and the singular string used as Reference.entity_type.
ENTITY_CONFIG = {
    "characters": {"table": scene_characters, "id_col": "character_id", "model": Character, "singular": "character"},
    "locations": {"table": scene_locations, "id_col": "location_id", "model": Location, "singular": "location"},
    "props": {"table": scene_props, "id_col": "prop_id", "model": Prop, "singular": "prop"},
}

VALID_ENTITY_TYPES = set(ENTITY_CONFIG.keys())


async def _validate_ref(db: AsyncSession, reference_id: str, entity_type: str, entity_id: str) -> None:
    ref = await db.get(Reference, reference_id)
    if not ref or ref.entity_type != entity_type or ref.entity_id != entity_id:
        raise LinkInvalid("Reference does not belong to this entity")


async def _primary_reference_id(db: AsyncSession, entity_type: str, entity_id: str) -> str | None:
    result = await db.execute(
        select(Reference.id)
        .where(
            Reference.entity_type == entity_type,
            Reference.entity_id == entity_id,
            Reference.role == "primary",
        )
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def load_scene_links(db: AsyncSession, scene_ids: list[str]) -> dict:
    """{scene_id: {"characters": [SceneEntityLink], "locations": [...], "props": [...]}}
    for every scene id, batched to keep serialization O(1) queries per type."""
    links = {sid: {"characters": [], "locations": [], "props": []} for sid in scene_ids}
    if not scene_ids:
        return links

    for plural, cfg in ENTITY_CONFIG.items():
        table = cfg["table"]
        id_col = table.c[cfg["id_col"]]
        result = await db.execute(
            select(
                table.c.scene_id,
                id_col.label("entity_id"),
                table.c.reference_id,
                Reference.processed_url,
                Reference.url,
            )
            .select_from(table.outerjoin(Reference, Reference.id == table.c.reference_id))
            .where(table.c.scene_id.in_(scene_ids))
        )
        for row in result:
            links[row.scene_id][plural].append(
                SceneEntityLink(
                    entity_id=row.entity_id,
                    reference_id=row.reference_id,
                    reference_url=row.processed_url or row.url,
                )
            )
    return links


def build_scene_response(scene: Scene, scene_links: dict) -> SceneResponse:
    """Serialize a loaded Scene and attach its per-scene entity links."""
    resp = SceneResponse.model_validate(scene)
    resp.character_links = scene_links.get("characters", [])
    resp.location_links = scene_links.get("locations", [])
    resp.prop_links = scene_links.get("props", [])
    return resp


async def link_entity(
    db: AsyncSession, scene_id: str, plural: str, entity_id: str, reference_id: str | None = None,
) -> None:
    cfg = ENTITY_CONFIG[plural]
    table, id_col_name, Model, singular = cfg["table"], cfg["id_col"], cfg["model"], cfg["singular"]

    scene = await db.get(Scene, scene_id)
    if not scene:
        raise LinkNotFound("Scene not found")
    entity = await db.get(Model, entity_id)
    if not entity:
        raise LinkNotFound(f"{singular.capitalize()} not found")
    if entity.project_id != scene.project_id:
        raise LinkInvalid("Entity does not belong to the scene's project")

    if reference_id is not None:
        await _validate_ref(db, reference_id, singular, entity_id)
    else:
        reference_id = await _primary_reference_id(db, singular, entity_id)

    existing = await db.execute(
        select(table).where(table.c.scene_id == scene_id, table.c[id_col_name] == entity_id)
    )
    if existing.first() is None:
        await db.execute(
            table.insert().values(scene_id=scene_id, **{id_col_name: entity_id, "reference_id": reference_id})
        )
        await db.commit()


async def set_entity_reference(
    db: AsyncSession, scene_id: str, plural: str, entity_id: str, reference_id: str | None,
) -> None:
    cfg = ENTITY_CONFIG[plural]
    table, id_col_name, singular = cfg["table"], cfg["id_col"], cfg["singular"]

    existing = await db.execute(
        select(table).where(table.c.scene_id == scene_id, table.c[id_col_name] == entity_id)
    )
    if existing.first() is None:
        raise LinkNotFound("Link not found")

    if reference_id is not None:
        await _validate_ref(db, reference_id, singular, entity_id)

    await db.execute(
        table.update()
        .where(table.c.scene_id == scene_id, table.c[id_col_name] == entity_id)
        .values(reference_id=reference_id)
    )
    await db.commit()


async def unlink_entity(db: AsyncSession, scene_id: str, plural: str, entity_id: str) -> bool:
    cfg = ENTITY_CONFIG[plural]
    table, id_col_name = cfg["table"], cfg["id_col"]
    result = await db.execute(
        table.delete().where(table.c.scene_id == scene_id, table.c[id_col_name] == entity_id)
    )
    await db.commit()
    return result.rowcount > 0

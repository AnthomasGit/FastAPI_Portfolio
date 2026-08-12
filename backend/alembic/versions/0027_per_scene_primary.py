"""per-scene primary images — migrate canonical/plate into scene links, drop the columns

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-12 00:00:00.000000

An asset's reference image is chosen PER SCENE, not once per project: the same
character wears different clothes in different scenes, and the same set can be
lit differently. The Reference + `scene_<type>.reference_id` schema was built
for exactly this from the start; `canonical_asset_image_id` / `plate_asset_image_id`
were added later and contradicted it, leaving two competing sources of truth.

This migration removes the global one, without losing the picks already made:

  1. For every entity with a canonical/plate image, ensure a Reference exists
     pointing at that AssetImage (find-or-create, matching the app's own
     assign-asset dedupe by asset_image_id).
  2. Point every scene link for that entity at that Reference, but ONLY where
     the scene has not already picked one — an explicit choice is never
     overwritten.
  3. Drop the three columns.

Generation then reads the scene's pick, falling back to the entity's newest
reference, so nothing has to be re-curated by hand.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (entity table, its canonical column, singular entity_type, link table, link fk)
_ENTITIES = [
    ("characters", "canonical_asset_image_id", "character", "scene_characters", "character_id"),
    ("props", "canonical_asset_image_id", "prop", "scene_props", "prop_id"),
    ("locations", "plate_asset_image_id", "location", "scene_locations", "location_id"),
    # A location's canonical is migrated too, but only fills a link the plate
    # did not already claim (the plate is the better establishing image).
    ("locations", "canonical_asset_image_id", "location", "scene_locations", "location_id"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for table, column, entity_type, link_table, link_fk in _ENTITIES:
        rows = conn.execute(sa.text(
            f"SELECT e.id AS entity_id, e.{column} AS asset_id, a.image_url "
            f"FROM {table} e JOIN asset_images a ON a.id = e.{column} "
            f"WHERE e.{column} IS NOT NULL"
        )).mappings().all()

        for row in rows:
            # 1. find-or-create the Reference for this asset image.
            ref_id = conn.execute(sa.text(
                "SELECT id FROM \"references\" WHERE entity_type = :et "
                "AND entity_id = :eid AND asset_image_id = :aid LIMIT 1"
            ), {"et": entity_type, "eid": row["entity_id"], "aid": row["asset_id"]}).scalar()

            if ref_id is None:
                ref_id = str(__import__("uuid").uuid4())
                conn.execute(sa.text(
                    "INSERT INTO \"references\" "
                    "(id, entity_type, entity_id, role, url, asset_image_id, sort_order, created_at) "
                    "VALUES (:id, :et, :eid, 'moodboard', :url, :aid, 0, CURRENT_TIMESTAMP)"
                ), {"id": ref_id, "et": entity_type, "eid": row["entity_id"],
                    "url": row["image_url"], "aid": row["asset_id"]})

            # 2. fill only the links that have not chosen for themselves.
            conn.execute(sa.text(
                f"UPDATE {link_table} SET reference_id = :ref "
                f"WHERE {link_fk} = :eid AND reference_id IS NULL"
            ), {"ref": ref_id, "eid": row["entity_id"]})

    # 3. the global columns are now redundant.
    op.drop_column("characters", "canonical_asset_image_id")
    op.drop_column("props", "canonical_asset_image_id")
    op.drop_column("locations", "canonical_asset_image_id")
    op.drop_column("locations", "plate_asset_image_id")


def downgrade() -> None:
    """Restore the columns and best-effort repopulate them from scene links.

    Lossy by nature: a per-scene model has more information than a single global
    pointer, so an entity used differently in two scenes collapses to whichever
    link is found first.
    """
    op.add_column("characters", sa.Column("canonical_asset_image_id", sa.String(), nullable=True))
    op.add_column("props", sa.Column("canonical_asset_image_id", sa.String(), nullable=True))
    op.add_column("locations", sa.Column("canonical_asset_image_id", sa.String(), nullable=True))
    op.add_column("locations", sa.Column("plate_asset_image_id", sa.String(), nullable=True))

    conn = op.get_bind()
    for table, column, entity_type, link_table, link_fk in (
        ("characters", "canonical_asset_image_id", "character", "scene_characters", "character_id"),
        ("props", "canonical_asset_image_id", "prop", "scene_props", "prop_id"),
        ("locations", "plate_asset_image_id", "location", "scene_locations", "location_id"),
    ):
        conn.execute(sa.text(
            f"UPDATE {table} SET {column} = ("
            f"  SELECT r.asset_image_id FROM {link_table} l "
            f"  JOIN \"references\" r ON r.id = l.reference_id "
            f"  WHERE l.{link_fk} = {table}.id AND r.asset_image_id IS NOT NULL LIMIT 1)"
        ))

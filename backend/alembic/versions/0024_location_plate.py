"""location background plate (Phase 4, KAN-41)

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-05 00:00:00.000000

Adds `plate_asset_image_id` (FK asset_images, SET NULL) to Location — a wide,
character-free establishing render reused as the background across every scene
set in that location. Kept separate from `canonical_asset_image_id` (the hero
identity image from KAN-32/36).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("plate_asset_image_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_locations_plate_asset_image",
        "locations", "asset_images",
        ["plate_asset_image_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_locations_plate_asset_image", "locations", type_="foreignkey")
    op.drop_column("locations", "plate_asset_image_id")

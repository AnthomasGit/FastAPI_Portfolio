"""consistency profiles — prompt/style profiles + canonical image (Phase 2, KAN-32)

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-05 00:00:00.000000

Adds the columns Phase 2 composes prompts from: a per-entity `prompt_profile`
(fixed, repeatable visual tokens) on Character/Location/Prop, a project-level
`style_profile`, and each entity's `canonical_asset_image_id` "hero" image
(FK asset_images, SET NULL) used as an identity reference in KAN-36.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTITIES = ("characters", "locations", "props")


def upgrade() -> None:
    op.add_column("projects", sa.Column("style_profile", sa.JSON(), nullable=True))
    for table in _ENTITIES:
        op.add_column(table, sa.Column("prompt_profile", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("canonical_asset_image_id", sa.String(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_canonical_asset_image",
            table, "asset_images",
            ["canonical_asset_image_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in _ENTITIES:
        op.drop_constraint(f"fk_{table}_canonical_asset_image", table, type_="foreignkey")
        op.drop_column(table, "canonical_asset_image_id")
        op.drop_column(table, "prompt_profile")
    op.drop_column("projects", "style_profile")

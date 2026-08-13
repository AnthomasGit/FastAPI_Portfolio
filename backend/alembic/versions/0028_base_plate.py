"""identity base plate — the image generations EDIT FROM

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-12 00:00:00.000000

This is NOT a revert of 0027. That migration removed the global "which image
represents this entity" pointer, because the answer is per scene — the same
character wears different clothes in different scenes. That stays gone.

This column answers a different question: **which image does a generation edit
FROM?** Sheets run img2img through an image-edit model, and until now they
resolved their source as "the entity's newest reference". That is whatever
happened to be generated last, which in practice meant a full scene still —
measured: a character sheet edited a living-room frame and returned the subject
still sitting on the sofa, because an edit model preserves what it is given.

The two axes are independent and both are needed:

  scene_<type>.reference_id  -> how they LOOK in this scene   (per scene)
  base_asset_image_id        -> what generations EDIT FROM    (per entity)

Nullable, and left NULL for every existing row: a NULL plate means "generate one
from the prompt on first use", which is exactly the desired behaviour for
entities that have never had one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("characters", "props")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("base_asset_image_id", sa.String(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "base_asset_image_id")

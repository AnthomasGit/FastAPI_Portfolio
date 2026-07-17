"""normal_map_url + seg_map_url columns on scene_captures

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scene_captures", sa.Column("normal_map_url", sa.String(), nullable=True))
    op.add_column("scene_captures", sa.Column("seg_map_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("scene_captures", "seg_map_url")
    op.drop_column("scene_captures", "normal_map_url")

"""color_map_url column on scene_captures

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scene_captures", sa.Column("color_map_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("scene_captures", "color_map_url")

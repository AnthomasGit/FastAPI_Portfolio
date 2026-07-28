"""backdrop_transform column on scene_stagings + staging_saves

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scene_stagings", sa.Column("backdrop_transform", sa.JSON(), nullable=True))
    op.add_column("staging_saves", sa.Column("backdrop_transform", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("staging_saves", "backdrop_transform")
    op.drop_column("scene_stagings", "backdrop_transform")

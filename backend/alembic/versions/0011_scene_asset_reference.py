"""per-scene reference_id on scene_characters / scene_locations / scene_props

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-18 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("scene_characters", "scene_locations", "scene_props")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("reference_id", sa.String(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_reference_id",
            table, "references",
            ["reference_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"fk_{table}_reference_id", table, type_="foreignkey")
        op.drop_column(table, "reference_id")

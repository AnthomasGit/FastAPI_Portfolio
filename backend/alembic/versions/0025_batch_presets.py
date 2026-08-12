"""batch presets (Phase 5, KAN-48)

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-11 00:00:00.000000

Adds `batch_presets`: a saved BatchCreateRequest spec, re-run with optional
overrides. A null `project_id` is a global preset shared across projects.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_presets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batch_presets_project_id", "batch_presets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_batch_presets_project_id", table_name="batch_presets")
    op.drop_table("batch_presets")

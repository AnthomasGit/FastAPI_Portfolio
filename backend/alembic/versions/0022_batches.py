"""batches — a named group of jobs (Phase 1, KAN-25)

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-05 00:00:00.000000

Creates the `batches` table and promotes the existing `jobs.batch_id` column
(added as a bare string in 0021) into a real FK → batches.id (SET NULL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("run_after", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_foreign_key(
        "fk_jobs_batch_id", "jobs", "batches",
        ["batch_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_batch_id", "jobs", type_="foreignkey")
    op.drop_table("batches")

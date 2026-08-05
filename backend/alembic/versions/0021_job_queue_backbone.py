"""job queue backbone — promote JobRecord into a real job table (Phase 0, KAN-18)

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-04 00:00:00.000000

Adds the columns the background worker needs: a handler dispatch `kind`, a JSON
`payload`, retry/priority/scheduling bookkeeping, a self-referential
`depends_on_job_id` for chaining, and a nullable `batch_id` (the Batch table
itself lands in Phase 1). Also relaxes the legacy `model_name`/`query` columns
to nullable — new job kinds do not populate them — and indexes the worker's
claim query on (status, priority, scheduled_after).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("kind", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), nullable=False,
                                    server_default="0"))
    op.add_column("jobs", sa.Column("max_attempts", sa.Integer(), nullable=False,
                                    server_default="3"))
    op.add_column("jobs", sa.Column("priority", sa.Integer(), nullable=False,
                                    server_default="0"))
    op.add_column("jobs", sa.Column("batch_id", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("depends_on_job_id", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("scheduled_after", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_foreign_key(
        "fk_jobs_depends_on_job_id", "jobs", "jobs",
        ["depends_on_job_id"], ["job_id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_jobs_claim", "jobs", ["status", "priority", "scheduled_after"],
    )

    # Legacy image-job columns become optional for non-image kinds.
    op.alter_column("jobs", "model_name", existing_type=sa.String(), nullable=True)
    op.alter_column("jobs", "query", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("jobs", "query", existing_type=sa.Text(), nullable=False)
    op.alter_column("jobs", "model_name", existing_type=sa.String(), nullable=False)

    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_constraint("fk_jobs_depends_on_job_id", "jobs", type_="foreignkey")

    op.drop_column("jobs", "updated_at")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "scheduled_after")
    op.drop_column("jobs", "depends_on_job_id")
    op.drop_column("jobs", "batch_id")
    op.drop_column("jobs", "priority")
    op.drop_column("jobs", "max_attempts")
    op.drop_column("jobs", "attempts")
    op.drop_column("jobs", "payload")
    op.drop_column("jobs", "kind")

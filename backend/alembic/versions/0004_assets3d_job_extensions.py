"""assets_3d table + JobRecord extensions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assets_3d",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("source_reference_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("mesh_url", sa.String(), nullable=True),
        sa.Column("rigged_mesh_url", sa.String(), nullable=True),
        sa.Column("preview_url", sa.String(), nullable=True),
        sa.Column("mesh_job_id", sa.String(), nullable=True),
        sa.Column("rig_job_id", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_reference_id"], ["references.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets3d_entity", "assets_3d", ["entity_type", "entity_id"])

    op.add_column("jobs", sa.Column("job_type", sa.String(), nullable=False, server_default="image"))
    op.add_column("jobs", sa.Column("entity_type", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("entity_id", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("finished_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "finished_at")
    op.drop_column("jobs", "error")
    op.drop_column("jobs", "entity_id")
    op.drop_column("jobs", "entity_type")
    op.drop_column("jobs", "job_type")
    op.drop_index("ix_assets3d_entity", table_name="assets_3d")
    op.drop_table("assets_3d")

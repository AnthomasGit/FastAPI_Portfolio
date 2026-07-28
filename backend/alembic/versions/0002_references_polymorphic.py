"""polymorphic_references

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-05 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("references")
    op.drop_column("characters", "reference_url")
    op.create_table(
        "references",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="moodboard"),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("processed_url", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_references_entity", "references", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_references_entity", table_name="references")
    op.drop_table("references")
    op.add_column("characters", sa.Column("reference_url", sa.String(), nullable=True))
    op.create_table(
        "references",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

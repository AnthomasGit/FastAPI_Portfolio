"""driving_videos — reusable motion-source clips for pose-transfer workflows

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-02 14:00:00.000000

SCAIL-2 is driven by an uploaded video, not a text prompt. Rather than upload
one per generation, they persist as a reusable library (like asset_images):
origin_project_id is nullable so a clip is pickable across projects. The file
itself lives flat in COMFY_INPUT_DIR; only its metadata is tracked here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driving_videos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("origin_project_id", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("video_url", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["origin_project_id"], ["projects.id"], ondelete="SET NULL"
        ),
    )


def downgrade() -> None:
    op.drop_table("driving_videos")

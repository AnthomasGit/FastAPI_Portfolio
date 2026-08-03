"""reference_audios — reusable audio clips for reference-to-video (MiniMax H3 R2V)

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-03 00:00:00.000000

R2V can take up to 3 standalone audio clips (voice/soundtrack references)
alongside its reference images and videos. Mirrors driving_videos: a reusable
library keyed off a nullable origin_project_id, with the file itself living
flat in COMFY_INPUT_DIR and only its metadata tracked here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_audios",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("origin_project_id", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("audio_url", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["origin_project_id"], ["projects.id"], ondelete="SET NULL"
        ),
    )


def downgrade() -> None:
    op.drop_table("reference_audios")

"""generated_videos.shot_id — clips that need no source still

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-31 06:00:00.000000

Until now a clip was always derived from a beauty-pass still, so a shot found
its clips through generated_image_id -> GeneratedImage.videos. The LTX-2.3 MSR
workflow composes reference images directly and needs no still at all, leaving
its clip with nothing to hang off. shot_id gives those attempts a home without
disturbing the image-to-video path, which keeps using source_image_id. Both
columns are nullable; in practice exactly one is set per row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generated_videos",
        sa.Column("shot_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_generated_videos_shot_id", "generated_videos", ["shot_id"]
    )
    op.create_foreign_key(
        "fk_generated_videos_shot_id",
        "generated_videos",
        "shots",
        ["shot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_generated_videos_shot_id", "generated_videos", type_="foreignkey"
    )
    op.drop_index("ix_generated_videos_shot_id", table_name="generated_videos")
    op.drop_column("generated_videos", "shot_id")

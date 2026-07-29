"""shots table (master shot list)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("shot_number", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("shot_size", sa.String(), nullable=True),
        sa.Column("angle", sa.String(), nullable=True),
        sa.Column("movement", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("equipment", sa.String(), nullable=True),
        sa.Column("audio_notes", sa.Text(), nullable=True),
        sa.Column("capture_id", sa.String(), nullable=True),
        sa.Column("generated_image_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capture_id"], ["scene_captures.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_image_id"], ["generated_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shots_scene", "shots", ["scene_id"])


def downgrade() -> None:
    op.drop_index("ix_shots_scene", table_name="shots")
    op.drop_table("shots")

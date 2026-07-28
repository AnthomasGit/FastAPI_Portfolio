"""scene_stagings + scene_captures tables, GeneratedImage extensions

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scene_stagings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("backdrop_reference_id", sa.String(), nullable=True),
        sa.Column("camera", sa.JSON(), nullable=True),
        sa.Column("blockout", sa.JSON(), nullable=True),
        sa.Column("placements", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["backdrop_reference_id"], ["references.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id"),
    )

    op.create_table(
        "scene_captures",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("staging_id", sa.String(), nullable=False),
        sa.Column("camera", sa.JSON(), nullable=False),
        sa.Column("staging_snapshot", sa.JSON(), nullable=False),
        sa.Column("depth_map_url", sa.String(), nullable=False),
        sa.Column("edge_map_url", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["staging_id"], ["scene_stagings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("generated_images", sa.Column("capture_id", sa.String(), nullable=True))
    op.add_column("generated_images", sa.Column("kind", sa.String(), nullable=False, server_default="txt2img"))
    op.add_column("generated_images", sa.Column("params", sa.JSON(), nullable=True))
    op.add_column("generated_images", sa.Column("error", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_generated_images_capture_id",
        "generated_images", "scene_captures",
        ["capture_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_generated_images_capture_id", "generated_images", type_="foreignkey")
    op.drop_column("generated_images", "error")
    op.drop_column("generated_images", "params")
    op.drop_column("generated_images", "kind")
    op.drop_column("generated_images", "capture_id")
    op.drop_table("scene_captures")
    op.drop_table("scene_stagings")

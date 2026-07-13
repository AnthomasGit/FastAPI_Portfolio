"""asset_images

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_images",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("origin_project_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="txt2img"),
        sa.Column("source_reference_id", sa.String(), nullable=True),
        sa.Column("source_asset_image_id", sa.String(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("prompt_id", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["origin_project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_reference_id"], ["references.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_asset_image_id"], ["asset_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "references",
        sa.Column("asset_image_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_references_asset_image_id",
        "references", "asset_images",
        ["asset_image_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_references_asset_image_id", "references", type_="foreignkey")
    op.drop_column("references", "asset_image_id")
    op.drop_table("asset_images")

"""asset3d web mesh columns (web_mesh_url, web_status)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-24 00:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets_3d", sa.Column("web_mesh_url", sa.String(), nullable=True))
    op.add_column("assets_3d", sa.Column("web_status", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets_3d", "web_status")
    op.drop_column("assets_3d", "web_mesh_url")

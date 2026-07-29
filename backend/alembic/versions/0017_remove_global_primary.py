"""remove global primary — primary is per-scene only

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-29 18:00:00.000000

Supersedes 0016's "one global primary per entity" model. Primary is now
per-scene only: scene_X.reference_id (migration 0011) is the sole source of
truth for which reference generates an asset in a given scene, so the same
character can wear different clothing across scenes. Entity-level
role='primary' is retired; references are an untyped-by-primary pool
(moodboard, tpose, turnaround, texture_ref, ...).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_reference_one_primary", table_name="references")
    op.execute("UPDATE \"references\" SET role = 'moodboard' WHERE role = 'primary'")


def downgrade() -> None:
    # Data direction is lossy (which ref was "primary" isn't recoverable);
    # just restore the constraint shape so 0016 can re-apply its own upgrade.
    op.create_index(
        "uq_reference_one_primary",
        "references",
        ["entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("role = 'primary'"),
    )

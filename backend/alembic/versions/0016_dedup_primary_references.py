"""dedup primary references + enforce one primary per entity

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-29 12:00:00.000000

Primary is the entity's single canonical/default reference (the per-scene
source of truth is scene_X.reference_id, already one-per-scene via migration
0011). This closes the gap that let two references both be role='primary'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep the most-recently-created primary per (entity_type, entity_id);
    # demote the rest to 'moodboard'. Tiebreak on id for equal timestamps.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY entity_type, entity_id
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM "references"
            WHERE role = 'primary'
        )
        UPDATE "references"
        SET role = 'moodboard'
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.create_index(
        "uq_reference_one_primary",
        "references",
        ["entity_type", "entity_id"],
        unique=True,
        postgresql_where=sa.text("role = 'primary'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reference_one_primary", table_name="references")

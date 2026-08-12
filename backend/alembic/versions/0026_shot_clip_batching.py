"""shot-clip batching — per-shot R2V refs, audio, dialogue, prompt, review markers

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-12 00:00:00.000000

Supports the shot-clip batch revamp: the batch unit becomes one MiniMax H3
reference-to-video clip per shot.

On `shots`:
  reference_audio_id — the audio FILE for the graph's LoadAudio slot (distinct
                       from the existing `audio_notes` planning text).
  audio_role         — 'dialogue' (audio carries the lines) | 'timbre' (voice
                       reference only). Drives the H3 prompt's task-type prefix
                       and retention marker.
  dialogue           — [{speaker_id, entity_id, language, text}], LLM-extracted
                       from the screenplay, user-editable.
  clip_refs          — ordered [{entity_type, entity_id}] override of which
                       assets fill the reference slots (null = computed default).
  clip_prompt        — the composed six-section H3 document, user-editable.

Plus review/commit markers: `generated_videos.approved_at` and
`batches.committed_at`.

All columns are nullable and additive — no backfill, no data migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shots", sa.Column("reference_audio_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_shots_reference_audio",
        "shots", "reference_audios",
        ["reference_audio_id"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column("shots", sa.Column("audio_role", sa.String(), nullable=True))
    op.add_column("shots", sa.Column("dialogue", sa.JSON(), nullable=True))
    op.add_column("shots", sa.Column("clip_refs", sa.JSON(), nullable=True))
    op.add_column("shots", sa.Column("clip_prompt", sa.Text(), nullable=True))

    op.add_column("generated_videos", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("batches", sa.Column("committed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("batches", "committed_at")
    op.drop_column("generated_videos", "approved_at")

    op.drop_constraint("fk_shots_reference_audio", "shots", type_="foreignkey")
    op.drop_column("shots", "clip_prompt")
    op.drop_column("shots", "clip_refs")
    op.drop_column("shots", "dialogue")
    op.drop_column("shots", "audio_role")
    op.drop_column("shots", "reference_audio_id")

"""Transcript emails (W-03): when the last one was sent, for the cooldown.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("transcript_sent_at", sa.DateTime(timezone=True)),
        schema="conversation",
    )


def downgrade() -> None:
    op.drop_column("conversations", "transcript_sent_at", schema="conversation")

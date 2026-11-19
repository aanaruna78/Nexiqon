"""Escalation queue and staff replies (ST-16).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

S = "conversation"


def upgrade() -> None:
    op.add_column("conversations", sa.Column("queue_status", sa.String(16)), schema=S)
    op.add_column("conversations", sa.Column("assignee", sa.String(200)), schema=S)
    op.add_column("conversations", sa.Column("resolved_at", sa.DateTime(timezone=True)), schema=S)
    op.create_index(
        "ix_conversation_conversations_queue_status", "conversations", ["queue_status"], schema=S
    )
    # Conversations already handed over join the queue.
    op.execute(f"UPDATE {S}.conversations SET queue_status = 'open' WHERE status = 'escalated'")


def downgrade() -> None:
    op.drop_index("ix_conversation_conversations_queue_status", "conversations", schema=S)
    for column in ("resolved_at", "assignee", "queue_status"):
        op.drop_column("conversations", column, schema=S)

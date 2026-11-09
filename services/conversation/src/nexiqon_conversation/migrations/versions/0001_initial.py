"""Conversation schema: conversations, messages, feedback, outbox + RLS + retention sweep policy.

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import extra_policy_sql, rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "conversation"
TS = sa.DateTime(timezone=True)
# The sweep may see and delete only conversations whose retention has expired, and only when
# trusted code sets app.retention_sweep for the transaction.
SWEEP = "retain_until < now() AND current_setting('app.retention_sweep', true) = 'on'"


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "conversations",
        *_base(),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("handoff_summary", sa.Text()),
        sa.Column("last_message_at", TS),
        sa.Column("retain_until", TS, index=True),
        schema=S,
    )
    op.create_table(
        "messages",
        *_base(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("contract", pg.JSONB(), nullable=False),
        sa.Column("run_id", sa.Uuid()),
        schema=S,
    )
    op.create_table(
        "feedback",
        *_base(),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.messages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("comment", sa.String(2000)),
        schema=S,
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("type", sa.String(200), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("subject", sa.String(500)),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("published_at", TS, index=True),
        sa.Column("traceparent", sa.String(64)),
        schema=S,
    )
    for table in ("conversations", "messages", "feedback"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)
    for stmt in extra_policy_sql(
        "conversations", S, "retention_sweep_select", SWEEP, command="SELECT"
    ):
        op.execute(stmt)
    for stmt in extra_policy_sql(
        "conversations", S, "retention_sweep_delete", SWEEP, command="DELETE"
    ):
        op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", "feedback", "messages", "conversations"):
        op.drop_table(table, schema=S)

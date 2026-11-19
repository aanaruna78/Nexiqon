"""metering schema: processed events, usage and activity rollups, conversation facts, budgets,
alerts, outbox + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "metering"
TS = sa.DateTime(timezone=True)
TABLES = (
    "processed_events",
    "usage_daily",
    "activity_daily",
    "conversation_facts",
    "budgets",
    "budget_alerts",
)


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "processed_events",
        *_base(),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(200), nullable=False),
        sa.UniqueConstraint("event_id"),
        schema=S,
    )
    op.create_table(
        "usage_daily",
        *_base(),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("profile", sa.String(63), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(16, 6), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "day", "agent", "operation", "profile", "provider", "model"
        ),
        schema=S,
    )
    op.create_table(
        "activity_daily",
        *_base(),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "day", "agent", "metric"),
        schema=S,
    )
    op.create_table(
        "conversation_facts",
        *_base(),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(63), nullable=False, index=True),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("answered", sa.Boolean(), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("rated_down", sa.Boolean(), nullable=False),
        sa.Column("events", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "conversation_id"),
        schema=S,
    )
    op.create_table(
        "budgets",
        *_base(),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("monthly_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("thresholds", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "agent"),
        schema=S,
    )
    op.create_table(
        "budget_alerts",
        *_base(),
        sa.Column("budget_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("threshold", sa.Numeric(4, 2), nullable=False),
        sa.Column("spent_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("limit_usd", sa.Numeric(14, 2), nullable=False),
        sa.Column("acknowledged_at", TS),
        sa.Column("extra", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("budget_id", "month", "threshold"),
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
    for table in TABLES:
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", *reversed(TABLES)):
        op.drop_table(table, schema=S)

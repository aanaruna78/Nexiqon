"""Webhooks and their deliveries, in-app inbox (NT-01).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import extra_policy_sql, rls_policy_sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

S = "notification"
TS = sa.DateTime(timezone=True)


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "webhooks",
        *_base(),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("events", pg.JSONB(), nullable=False),
        sa.Column("secret", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        schema=S,
    )
    op.create_table(
        "webhook_deliveries",
        *_base(),
        sa.Column(
            "webhook_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.webhooks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("error", sa.String(500)),
        sa.Column("next_attempt_at", TS, index=True),
        sa.UniqueConstraint("webhook_id", "event_id"),
        schema=S,
    )
    op.create_table(
        "inbox_items",
        *_base(),
        sa.Column("kind", sa.String(63), nullable=False),
        sa.Column("roles", pg.JSONB(), nullable=False),
        sa.Column("params", pg.JSONB(), nullable=False),
        sa.Column("link", sa.String(500)),
        sa.Column("event_id", sa.Uuid()),
        schema=S,
    )
    op.create_table(
        "inbox_reads",
        *_base(),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.inbox_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.UniqueConstraint("item_id", "actor_id"),
        schema=S,
    )
    for table in ("webhooks", "webhook_deliveries", "inbox_items", "inbox_reads"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)
    # The retry loop finds due deliveries across tenants (ids only, then works per tenant).
    for stmt in extra_policy_sql(
        "webhook_deliveries",
        S,
        "retry_sweep_select",
        "status = 'pending' AND current_setting('app.webhook_sweep', true) = 'on'",
        command="SELECT",
    ):
        op.execute(stmt)


def downgrade() -> None:
    for table in ("inbox_reads", "inbox_items", "webhook_deliveries", "webhooks"):
        op.drop_table(table, schema=S)

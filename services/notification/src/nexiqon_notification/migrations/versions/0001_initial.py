"""notification schema: delivery log, outbox + RLS.

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

S = "notification"
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(63), nullable=False, index=True),
        sa.Column("reference", sa.String(200)),
        sa.Column("recipient_hash", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500)),
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
    for stmt in rls_policy_sql("deliveries", S):
        op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", "deliveries"):
        op.drop_table(table, schema=S)

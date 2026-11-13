"""tool-gateway schema: tool call log, approvals, outbox + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "tool_gateway"
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
        "tool_calls",
        *_base(),
        sa.Column("tool", sa.String(63), nullable=False, index=True),
        sa.Column("tool_version", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("conversation_id", sa.String(100)),
        sa.Column("risk", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(200)),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("arguments", pg.JSONB(), nullable=False),
        sa.Column("result", pg.JSONB()),
        sa.Column("approval_id", sa.Uuid()),
        sa.UniqueConstraint("tenant_id", "tool", "idempotency_key"),
        schema=S,
    )
    op.create_table(
        "approvals",
        *_base(),
        sa.Column("tool", sa.String(63), nullable=False, index=True),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("conversation_id", sa.String(100)),
        sa.Column("arguments", pg.JSONB(), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("decided_by", sa.String(200)),
        sa.Column("decided_at", TS),
        sa.Column("expires_at", TS, nullable=False),
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
    for table in ("tool_calls", "approvals"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", "approvals", "tool_calls"):
        op.drop_table(table, schema=S)

"""Model gateway schema: usage records (no prompt text) + outbox, with RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "model_gateway"
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("profile", sa.String(63), nullable=False, index=True),
        sa.Column("requested_profile", sa.String(63), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("conversation_id", sa.String(200), index=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("priced", sa.Boolean(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        schema=S,
    )
    # Budget checks sum a tenant's month by profile.
    op.create_index(
        "ix_usage_records_tenant_profile_created",
        "usage_records",
        ["tenant_id", "profile", "created_at"],
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
    for stmt in rls_policy_sql("usage_records", S):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("outbox_events", schema=S)
    op.drop_table("usage_records", schema=S)

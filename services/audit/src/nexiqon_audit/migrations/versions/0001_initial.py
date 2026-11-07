"""Audit schema: append-only, hash-chained audit events + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "audit"
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(200), nullable=False, index=True),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("subject", sa.String(500)),
        sa.Column("actor_id", sa.String(200), nullable=False, index=True),
        sa.Column("occurred_at", TS, nullable=False, index=True),
        sa.Column("data", pg.JSONB(), nullable=False),
        sa.Column("traceparent", sa.String(64)),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "seq"),
        sa.UniqueConstraint("event_id"),
        schema=S,
    )
    # Append-only: no updates; deletes only inside the tenant-deletion saga.
    op.execute(f"""
        CREATE FUNCTION {S}.append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('app.tenant_deletion', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = 'check_violation';
        END $$
    """)
    op.execute(f"""
        CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON {S}.audit_events
        FOR EACH ROW EXECUTE FUNCTION {S}.append_only()
    """)
    for stmt in rls_policy_sql("audit_events", S):
        op.execute(stmt)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS append_only ON {S}.audit_events")
    op.execute(f"DROP FUNCTION IF EXISTS {S}.append_only()")
    op.drop_table("audit_events", schema=S)

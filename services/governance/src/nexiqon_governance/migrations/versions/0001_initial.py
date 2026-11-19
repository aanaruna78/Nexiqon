"""governance schema: lifecycle requests and steps, retention runs, known tenants, outbox + RLS.

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

S = "governance"
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
        "lifecycle_requests",
        *_base(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("run_after", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("result_key", sa.String(500)),
        sa.Column("error", sa.String(1000)),
        schema=S,
    )
    op.create_table(
        "lifecycle_steps",
        *_base(),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.lifecycle_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("service", sa.String(63), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("detail", pg.JSONB(), nullable=False),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint("request_id", "service"),
        schema=S,
    )
    op.create_table(
        "retention_runs",
        *_base(),
        sa.Column("started_by", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("policy", pg.JSONB(), nullable=False),
        sa.Column("purged", pg.JSONB(), nullable=False),
        sa.Column("errors", pg.JSONB(), nullable=False),
        sa.Column("finished_at", TS),
        schema=S,
    )
    op.create_table(
        "known_tenants",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("deleted_at", TS),
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
    for table in ("lifecycle_requests", "lifecycle_steps", "retention_runs"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in (
        "outbox_events",
        "known_tenants",
        "retention_runs",
        "lifecycle_steps",
        "lifecycle_requests",
    ):
        op.drop_table(table, schema=S)

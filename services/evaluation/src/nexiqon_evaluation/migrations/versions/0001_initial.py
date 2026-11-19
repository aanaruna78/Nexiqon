"""evaluation schema: test sets, cases, runs, results, outbox + RLS.

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

S = "evaluation"
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
        "test_sets",
        *_base(),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("agent", sa.String(63), index=True),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("evaluators", pg.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name"),
        schema=S,
    )
    op.create_table(
        "test_cases",
        *_base(),
        sa.Column(
            "test_set_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.test_sets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("question", sa.String(2000), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False),
        sa.Column("expected_source", sa.String(500)),
        sa.Column("expected_section", sa.String(500)),
        sa.Column("expected_phrases", pg.JSONB(), nullable=False),
        sa.Column("must_abstain", sa.Boolean(), nullable=False),
        sa.Column("origin", pg.JSONB(), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        schema=S,
    )
    op.create_table(
        "runs",
        *_base(),
        sa.Column("agent", sa.String(63), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "test_set_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.test_sets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("test_set_revision", sa.Integer(), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("started_by", sa.String(200), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("done_count", sa.Integer(), nullable=False),
        sa.Column("scorecard", pg.JSONB()),
        sa.Column("error", sa.String(1000)),
        sa.Column("finished_at", TS),
        schema=S,
    )
    op.create_table(
        "results",
        *_base(),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("case_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("question", sa.String(2000), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("kind", sa.String(32)),
        sa.Column("citations", pg.JSONB(), nullable=False),
        sa.Column("scores", pg.JSONB(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("agent_run_id", sa.String(64)),
        sa.Column("error", sa.String(1000)),
        sa.UniqueConstraint("run_id", "case_id"),
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
    for table in ("test_sets", "test_cases", "runs", "results"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", "results", "runs", "test_cases", "test_sets"):
        op.drop_table(table, schema=S)

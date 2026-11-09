"""agent-runtime schema: threads, runs, LangGraph checkpoints (blobs, writes) + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "agent_runtime"
TS = sa.DateTime(timezone=True)
TABLES = ("threads", "runs", "checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _base() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "threads",
        *_base(),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.UniqueConstraint("tenant_id", "thread_id"),
        schema=S,
    )
    op.create_table(
        "runs",
        *_base(),
        sa.Column("thread_id", sa.String(100), nullable=False, index=True),
        sa.Column("agent", sa.String(63), nullable=False),
        sa.Column("agent_versions", pg.JSONB(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("steps", pg.JSONB(), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("error", sa.String(1000)),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("finished_at", TS),
        schema=S,
    )
    op.create_table(
        "checkpoints",
        *_base(),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("checkpoint_ns", sa.String(200), nullable=False),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(64)),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("checkpoint", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.String(32), nullable=False),
        sa.Column("meta", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id"),
        schema=S,
    )
    op.create_table(
        "checkpoint_blobs",
        *_base(),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("checkpoint_ns", sa.String(200), nullable=False),
        sa.Column("channel", sa.String(200), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("blob", sa.LargeBinary()),
        sa.UniqueConstraint("tenant_id", "thread_id", "checkpoint_ns", "channel", "version"),
        schema=S,
    )
    op.create_table(
        "checkpoint_writes",
        *_base(),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("checkpoint_ns", sa.String(200), nullable=False),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("task_path", sa.String(500), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(200), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"
        ),
        schema=S,
    )
    for table in TABLES:
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=S)

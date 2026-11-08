"""Ingestion schema: collections, sources, documents, runs, outbox + RLS.

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

S = "ingestion"
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
        "collections",
        *_base(),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("model_profile", sa.String(63), nullable=False),
        sa.Column("retrieval_profile", sa.String(63), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("acl_groups", pg.ARRAY(sa.String(200)), nullable=False),
        sa.Column("embedding_model", sa.String(200)),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.UniqueConstraint("tenant_id", "name"),
        schema=S,
    )
    op.create_table(
        "sources",
        *_base(),
        sa.Column(
            "collection_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.collections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("connector", sa.String(63), nullable=False),
        sa.Column("config", pg.JSONB(), nullable=False),
        sa.Column("schedule_hours", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_run_id", sa.Uuid()),
        sa.Column("last_synced_at", TS),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.UniqueConstraint("collection_id", "name"),
        schema=S,
    )
    op.create_table(
        "documents",
        *_base(),
        sa.Column(
            "collection_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.collections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.sources.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("uri", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000)),
        sa.Column("media_type", sa.String(200)),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("source_version", sa.String(200)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("indexed_version", sa.Integer()),
        sa.Column("blob_key", sa.String(1000)),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_detail", sa.String(1000)),
        sa.Column("scanner", sa.String(32)),
        sa.Column("scan_signature", sa.String(200)),
        sa.Column("section_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid()),
        sa.Column("indexed_at", TS),
        sa.UniqueConstraint("source_id", "uri"),
        schema=S,
    )
    op.create_table(
        "runs",
        *_base(),
        sa.Column(
            "collection_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.collections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_id", sa.Uuid(), index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("workflow_id", sa.String(300)),
        *[
            sa.Column(c, sa.Integer(), nullable=False)
            for c in ("discovered", "processed", "unchanged", "failed", "quarantined", "deleted")
        ],
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("warnings", pg.JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("created_by", sa.String(200), nullable=False),
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
    for table in ("collections", "sources", "documents", "runs"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    for table in ("outbox_events", "runs", "documents", "sources", "collections"):
        op.drop_table(table, schema=S)

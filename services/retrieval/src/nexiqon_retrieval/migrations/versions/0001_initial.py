"""Retrieval index: document-tree nodes with pgvector embeddings, ltree paths, FTS + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import rls_policy_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "retrieval"
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.create_table(
        "index_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("path", sa.Text(), nullable=False),  # becomes ltree below
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(1000)),
        sa.Column("heading_path", pg.ARRAY(sa.String(1000)), nullable=False),
        sa.Column("heading_text", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("source_uri", sa.String(2000)),
        sa.Column("acl_groups", pg.ARRAY(sa.String(200)), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("embedding_model", sa.String(200)),
        sa.Column("embedding", Vector(1024)),
        schema=S,
    )
    t = f"{S}.index_nodes"
    op.execute(f"ALTER TABLE {t} ALTER COLUMN path TYPE ltree USING path::ltree")
    # Language-neutral keyword index ('simple'); language-aware configs arrive with search (RT-02).
    op.execute(
        f"ALTER TABLE {t} ADD COLUMN tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('simple', coalesce(title, '') || ' ' || heading_text || ' ' || text)) STORED"
    )
    op.execute(f"CREATE INDEX ix_index_nodes_tenant_collection ON {t} (tenant_id, collection_id)")
    op.execute(f"CREATE INDEX ix_index_nodes_tenant_document ON {t} (tenant_id, document_id)")
    op.execute(f"CREATE INDEX ix_index_nodes_parent ON {t} (parent_id)")
    op.execute(f"CREATE INDEX ix_index_nodes_path ON {t} USING gist (path)")
    op.execute(f"CREATE INDEX ix_index_nodes_tsv ON {t} USING gin (tsv)")
    op.execute(f"CREATE INDEX ix_index_nodes_acl ON {t} USING gin (acl_groups)")
    op.execute(
        f"CREATE INDEX ix_index_nodes_embedding ON {t} "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    for stmt in rls_policy_sql("index_nodes", S):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("index_nodes", schema=S)

"""Config schema: objects, versions (immutable once published), deployments, history, outbox + RLS.

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

S = "config"
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
        "config_objects",
        *_base(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("archived_at", TS),
        sa.UniqueConstraint("tenant_id", "kind", "name"),
        schema=S,
    )
    op.create_table(
        "config_versions",
        *_base(),
        sa.Column(
            "object_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.config_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", pg.JSONB(), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("published_by", sa.String(200)),
        sa.Column("published_at", TS),
        sa.UniqueConstraint("object_id", "version"),
        sa.CheckConstraint("status IN ('draft','published')", name="status"),
        schema=S,
    )
    # At most one draft per object.
    op.create_index(
        "ux_config_versions_one_draft",
        "config_versions",
        ["object_id"],
        unique=True,
        schema=S,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_table(
        "config_deployments",
        *_base(),
        sa.Column(
            "object_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.config_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey(f"{S}.config_versions.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deployed_by", sa.String(200), nullable=False),
        sa.UniqueConstraint("object_id", "environment"),
        sa.CheckConstraint("environment IN ('dev','staging','prod')", name="environment"),
        schema=S,
    )
    op.create_table(
        "deployment_history",
        *_base(),
        sa.Column(
            "object_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.config_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("from_version", sa.Integer()),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
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
        schema=S,
    )
    # Published versions are immutable. Only the tenant-deletion saga may remove them.
    op.execute(f"""
        CREATE FUNCTION {S}.protect_published_versions() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'published' THEN
            IF TG_OP = 'DELETE' AND current_setting('app.tenant_deletion', true) = 'on' THEN
              RETURN OLD;
            END IF;
            RAISE EXCEPTION 'published config versions are immutable' USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(f"""
        CREATE TRIGGER protect_published_versions BEFORE UPDATE OR DELETE ON {S}.config_versions
        FOR EACH ROW EXECUTE FUNCTION {S}.protect_published_versions()
    """)
    for table in ("config_objects", "config_versions", "config_deployments", "deployment_history"):
        for stmt in rls_policy_sql(table, S):
            op.execute(stmt)


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS protect_published_versions ON {S}.config_versions")
    op.execute(f"DROP FUNCTION IF EXISTS {S}.protect_published_versions()")
    for table in (
        "outbox_events",
        "deployment_history",
        "config_deployments",
        "config_versions",
        "config_objects",
    ):
        op.drop_table(table, schema=S)

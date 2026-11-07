"""Identity schema: tenants, users, memberships, groups, API keys, outbox + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexiqon_core.db import extra_policy_sql, rls_policy_sql, setting

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "identity"
TS = sa.DateTime(timezone=True)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def _tenant_scoped() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        *_timestamps(),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deployment_mode", sa.String(16), nullable=False),
        sa.Column("idp_provider", sa.String(64)),
        sa.Column("idp_org_ref", sa.String(200)),
        *_timestamps(),
        sa.UniqueConstraint("idp_provider", "idp_org_ref"),
        schema=S,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idp_issuer", sa.String(300), nullable=False),
        sa.Column("idp_subject", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), index=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column("last_login_at", TS),
        *_timestamps(),
        sa.UniqueConstraint("idp_issuer", "idp_subject"),
        schema=S,
    )
    op.create_table(
        "memberships",
        *_tenant_scoped(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey(f"{S}.users.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("invited_email", sa.String(320)),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("invited_by", sa.String(200)),
        sa.UniqueConstraint("tenant_id", "user_id"),
        sa.UniqueConstraint("tenant_id", "invited_email"),
        sa.CheckConstraint("role IN ('owner','admin','editor','member')", name="role"),
        sa.CheckConstraint("status IN ('invited','active','disabled')", name="status"),
        schema=S,
    )
    op.create_table(
        "groups",
        *_tenant_scoped(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.UniqueConstraint("tenant_id", "name"),
        schema=S,
    )
    op.create_table(
        "group_members",
        *_tenant_scoped(),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.Uuid(),
            sa.ForeignKey(f"{S}.memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("group_id", "membership_id"),
        schema=S,
    )
    op.create_table(
        "api_keys",
        *_tenant_scoped(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("roles", pg.JSONB(), nullable=False),
        sa.Column("allowed_origins", pg.JSONB(), nullable=False),
        sa.Column("agent_ids", pg.JSONB(), nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("revoked_at", TS),
        sa.Column("last_used_at", TS),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("meta", pg.JSONB(), nullable=False),
        sa.CheckConstraint("kind IN ('server','widget')", name="kind"),
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

    uid, email = setting("user_id"), setting("user_email", "text")
    statements: list[str] = []
    # tenants: a tenant sees itself; members see tenants they belong to; narrow lookups by slug/org.
    statements += rls_policy_sql("tenants", S, column="id")
    statements += extra_policy_sql(
        "tenants",
        S,
        "member_reads_tenant",
        f"id IN (SELECT tenant_id FROM {S}.memberships WHERE user_id = {uid} AND status = 'active')",
        command="SELECT",
    )
    statements += extra_policy_sql(
        "tenants", S, "lookup_by_slug", f"slug = {setting('tenant_slug', 'text')}", command="SELECT"
    )
    statements += extra_policy_sql(
        "tenants",
        S,
        "lookup_by_org",
        f"idp_provider = {setting('idp_provider', 'text')} AND idp_org_ref = {setting('idp_org_ref', 'text')}",
        command="SELECT",
    )
    # users: no tenant column. Self, login lookup (issuer+subject), and members of the current tenant.
    statements += [
        f"ALTER TABLE {S}.users ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {S}.users FORCE ROW LEVEL SECURITY",
    ]
    statements += extra_policy_sql("users", S, "self", f"id = {uid}", with_check=f"id = {uid}")
    login = f"idp_issuer = {setting('idp_issuer', 'text')} AND idp_subject = {setting('idp_subject', 'text')}"
    statements += extra_policy_sql("users", S, "login", login, with_check=login)
    statements += extra_policy_sql(
        "users",
        S,
        "tenant_members",
        f"id IN (SELECT user_id FROM {S}.memberships WHERE tenant_id = {setting('tenant_id')})",
        command="SELECT",
    )
    # memberships: tenant isolation + a user's own memberships + accepting an invite by verified email.
    statements += rls_policy_sql("memberships", S)
    statements += extra_policy_sql(
        "memberships", S, "self_read", f"user_id = {uid}", command="SELECT"
    )
    invite = f"status = 'invited' AND lower(invited_email) = {email}"
    statements += extra_policy_sql("memberships", S, "invite_read", invite, command="SELECT")
    statements += extra_policy_sql(
        "memberships",
        S,
        "invite_accept",
        invite,
        command="UPDATE",
        with_check=f"user_id = {uid} AND status = 'active'",
    )
    for table in ("groups", "group_members"):
        statements += rls_policy_sql(table, S)
    statements += rls_policy_sql("api_keys", S)
    statements += extra_policy_sql(
        "api_keys",
        S,
        "key_lookup",
        f"prefix = {setting('api_key_prefix', 'text')}",
        command="SELECT",
    )
    for stmt in statements:
        op.execute(stmt)


def downgrade() -> None:
    for table in (
        "outbox_events",
        "api_keys",
        "group_members",
        "groups",
        "memberships",
        "users",
        "tenants",
    ):
        op.drop_table(table, schema=S)

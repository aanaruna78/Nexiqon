"""Licence (DV-06): identity counts the installation's organizations to apply the licensed limit.

The policy is read-only and applies only while identity sets app.licence_count in the
transaction that creates an organization; it is used for a count, never to return rows.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""

from alembic import op

from nexiqon_core.db import extra_policy_sql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

S = "identity"


def upgrade() -> None:
    for stmt in extra_policy_sql(
        "tenants",
        S,
        "licence_count_select",
        "current_setting('app.licence_count', true) = 'on'",
        command="SELECT",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS licence_count_select ON {S}.tenants")

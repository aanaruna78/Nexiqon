"""Idempotency keys belong to one caller and assistant (QA3-01).

A replay used to be looked up by tenant, tool and key only, so another person reusing a key got
the first caller's stored result. Keys are now unique per (tenant, tool, assistant, actor, key).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_tool_calls_tenant_id_tool_idempotency_key", "tool_calls", schema="tool_gateway"
    )
    op.create_unique_constraint(
        "uq_tool_calls_tenant_id_tool_agent_actor_id_idempotency_key",
        "tool_calls",
        ["tenant_id", "tool", "agent", "actor_id", "idempotency_key"],
        schema="tool_gateway",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_tool_calls_tenant_id_tool_agent_actor_id_idempotency_key",
        "tool_calls",
        schema="tool_gateway",
    )
    op.create_unique_constraint(
        "uq_tool_calls_tenant_id_tool_idempotency_key",
        "tool_calls",
        ["tenant_id", "tool", "idempotency_key"],
        schema="tool_gateway",
    )

"""Usage attributed to an assistant (MT-01).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage_records", sa.Column("agent", sa.String(63)), schema="model_gateway")
    op.create_index(
        "ix_model_gateway_usage_records_agent", "usage_records", ["agent"], schema="model_gateway"
    )


def downgrade() -> None:
    op.drop_index("ix_model_gateway_usage_records_agent", "usage_records", schema="model_gateway")
    op.drop_column("usage_records", "agent", schema="model_gateway")

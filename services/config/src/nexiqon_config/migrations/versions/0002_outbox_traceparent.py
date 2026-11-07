"""Outbox rows carry the producer's W3C trace context.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("traceparent", sa.String(64)), schema="config")


def downgrade() -> None:
    op.drop_column("outbox_events", "traceparent", schema="config")

"""Runs record incomplete discovery (QA2-03): such runs never delete documents.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="ingestion",
    )


def downgrade() -> None:
    op.drop_column("runs", "incomplete", schema="ingestion")

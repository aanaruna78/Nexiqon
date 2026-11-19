"""Outdated documents (fix loop, ST-14): marked by a content manager, left out of answers until a
new version is indexed.

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

S = "retrieval"


def upgrade() -> None:
    op.add_column(
        "index_nodes",
        sa.Column("outdated", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema=S,
    )


def downgrade() -> None:
    op.drop_column("index_nodes", "outdated", schema=S)

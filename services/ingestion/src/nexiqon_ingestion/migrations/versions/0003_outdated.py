"""Documents marked outdated (fix loop, ST-14).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

S = "ingestion"


def upgrade() -> None:
    op.add_column("documents", sa.Column("outdated_at", sa.DateTime(timezone=True)), schema=S)
    op.add_column("documents", sa.Column("outdated_by", sa.String(200)), schema=S)


def downgrade() -> None:
    op.drop_column("documents", "outdated_by", schema=S)
    op.drop_column("documents", "outdated_at", schema=S)

"""Persist source extraction before writing context or graph evidence.

Revision ID: 202609220001
Revises: 202609210001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609220001"
down_revision = "202609210001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("analysis_checkpoint", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "analysis_checkpoint")

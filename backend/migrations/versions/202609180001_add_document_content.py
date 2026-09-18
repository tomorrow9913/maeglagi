"""Add extracted document content.

Revision ID: 202609180001
Revises: 202609170002
"""

import sqlalchemy as sa
from alembic import op

revision = "202609180001"
down_revision = "202609170002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("content_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "content_text")

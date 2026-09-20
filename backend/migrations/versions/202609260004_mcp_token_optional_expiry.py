"""Allow explicitly non-expiring MCP tokens.

Revision ID: 202609260004
Revises: 202609260003
"""

import sqlalchemy as sa
from alembic import op

revision = "202609260004"
down_revision = "202609260003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "mcp_tokens", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )


def downgrade() -> None:
    # A finite one-year deadline preserves access if an older binary is restored.
    op.execute(
        "UPDATE mcp_tokens SET expires_at = now() + interval '1 year' WHERE expires_at IS NULL"
    )
    op.alter_column(
        "mcp_tokens", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )

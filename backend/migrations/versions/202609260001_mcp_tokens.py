"""Account-owned, hashed and revocable MCP credentials."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609260001"
down_revision = "202609250001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_hint", sa.String(6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["owner_id"], ["auth.users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_mcp_tokens_owner_id", "mcp_tokens", ["owner_id"])
    op.execute("ALTER TABLE mcp_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON mcp_tokens FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON mcp_tokens FROM authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("mcp_tokens")

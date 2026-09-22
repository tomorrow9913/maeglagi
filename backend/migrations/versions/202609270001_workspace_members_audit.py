"""Add workspace membership and append-only audit events.

Revision ID: 202609270001
Revises: 202609260004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609270001"
down_revision = "202609260004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role in ('owner', 'admin', 'editor', 'viewer')", name="ck_workspace_members_role"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "email_normalized", name="uq_workspace_members_email"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_user"),
    )
    op.create_index("workspace_members_user_id_idx", "workspace_members", ["user_id"])
    op.create_index("workspace_members_email_idx", "workspace_members", ["email_normalized"])
    op.execute("""
        INSERT INTO workspace_members (
            id, workspace_id, user_id, email, email_normalized,
            role, invited_by, joined_at, created_at
        )
        SELECT gen_random_uuid(), id, owner_id, '', '', 'owner', owner_id, created_at, created_at
        FROM workspaces
    """)
    op.create_table(
        "workspace_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_email", sa.String(320), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "workspace_audit_events_workspace_created_idx",
        "workspace_audit_events",
        ["workspace_id", "created_at"],
    )
    op.create_index("workspace_audit_events_actor_idx", "workspace_audit_events", ["actor_id"])


def downgrade() -> None:
    op.drop_table("workspace_audit_events")
    op.drop_table("workspace_members")

"""Persist ingestion jobs for the optional PostgreSQL executor.

Revision ID: 202609240001
Revises: 202609230001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609240001"
down_revision = "202609230001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("provider_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_processing_jobs_status",
        ),
    )
    op.create_index("processing_jobs_ready_idx", "processing_jobs", ["status", "next_run_at"])
    op.create_index("processing_jobs_lease_idx", "processing_jobs", ["status", "lease_expires_at"])
    op.execute("ALTER TABLE processing_jobs ENABLE ROW LEVEL SECURITY")
    # Supabase projects can grant new public-schema tables to browser roles via
    # default privileges. This internal queue is accessed only by the API DB role.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON processing_jobs FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON processing_jobs FROM authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("processing_jobs")

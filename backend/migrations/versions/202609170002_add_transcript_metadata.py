"""Add meeting transcript metadata.

Revision ID: 202609170002
Revises: 202609170001
"""

import sqlalchemy as sa
from alembic import op

revision = "202609170002"
down_revision = "202609170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("transcript_source", sa.String(20), nullable=True))
    op.add_column("sources", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.add_column("sources", sa.Column("transcript_text", sa.Text(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("processing_stage", sa.String(20), nullable=False, server_default="uploaded"),
    )
    op.add_column("sources", sa.Column("progress", sa.Float(), nullable=False, server_default="0"))
    op.add_column("sources", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_sources_transcript_source",
        "sources",
        "transcript_source is null or transcript_source in ('server', 'browser')",
    )
    op.create_check_constraint(
        "ck_sources_duration_seconds",
        "sources",
        "duration_seconds is null or duration_seconds >= 0",
    )
    op.create_check_constraint("ck_sources_progress", "sources", "progress >= 0 and progress <= 1")


def downgrade() -> None:
    op.drop_constraint("ck_sources_progress", "sources", type_="check")
    op.drop_constraint("ck_sources_duration_seconds", "sources", type_="check")
    op.drop_constraint("ck_sources_transcript_source", "sources", type_="check")
    op.drop_column("sources", "transcript_text")
    op.drop_column("sources", "duration_seconds")
    op.drop_column("sources", "transcript_source")
    op.drop_column("sources", "error_message")
    op.drop_column("sources", "progress")
    op.drop_column("sources", "processing_stage")

"""Keep externally analyzed sources out of server AI queues.

Revision ID: 202609260002
Revises: 202609260001
"""

import sqlalchemy as sa
from alembic import op

revision = "202609260002"
down_revision = "202609260001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("analysis_mode", sa.String(16), nullable=False, server_default="server"),
    )
    op.create_check_constraint(
        "ck_sources_analysis_mode",
        "sources",
        "analysis_mode in ('server', 'agent')",
    )
    op.drop_constraint("ck_sources_transcript_source", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_transcript_source",
        "sources",
        "transcript_source is null or transcript_source in ('server', 'browser', 'agent')",
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM sources WHERE analysis_mode = 'agent'"))
        .scalar_one()
    ):
        raise RuntimeError("Cannot remove agent source mode while agent sources exist")
    op.drop_constraint("ck_sources_transcript_source", "sources", type_="check")
    op.create_check_constraint(
        "ck_sources_transcript_source",
        "sources",
        "transcript_source is null or transcript_source in ('server', 'browser')",
    )
    op.drop_constraint("ck_sources_analysis_mode", "sources", type_="check")
    op.drop_column("sources", "analysis_mode")

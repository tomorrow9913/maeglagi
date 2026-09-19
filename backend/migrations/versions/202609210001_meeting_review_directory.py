"""Workspace directory and meeting review gate.

Revision ID: 202609210001
Revises: 202609200001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609210001"
down_revision = "202609200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(120)),
        sa.Column("aliases", postgresql.JSONB(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("workspace_people_workspace_id_idx", "workspace_people", ["workspace_id"])
    op.execute("ALTER TABLE workspace_people ENABLE ROW LEVEL SECURITY")
    op.create_table(
        "workspace_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column(
            "owner_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_people.id", ondelete="SET NULL"),
        ),
        sa.Column("starts_on", sa.Date()),
        sa.Column("ends_on", sa.Date()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("workspace_projects_workspace_id_idx", "workspace_projects", ["workspace_id"])
    op.execute("ALTER TABLE workspace_projects ENABLE ROW LEVEL SECURITY")
    op.add_column("sources", sa.Column("raw_transcript_text", sa.Text()))
    op.add_column(
        "sources",
        sa.Column(
            "raw_utterances",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "review_utterances",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("sources", sa.Column("review_state", sa.String(24)))
    op.add_column(
        "sources", sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "sources",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_projects.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("sources", sa.Column("confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("sources", sa.Column("confirmed_snapshot", postgresql.JSONB()))
    # Existing processed meeting sources predate the review gate. Keep their
    # transcript available in the review viewer without claiming it was edited.
    op.execute(
        "UPDATE sources SET review_state = 'confirmed', "
        "review_utterances = CASE WHEN nullif(trim(transcript_text), '') IS NULL THEN '[]'::jsonb "
        "ELSE jsonb_build_array(jsonb_build_object('id', 'legacy-0', 'personId', null, "
        "'speakerName', '화자 1', 'text', transcript_text, "
        "'startSeconds', 0, 'endSeconds', duration_seconds)) END "
        "WHERE kind = 'meeting' AND status = 'succeeded'"
    )
    # A prior worker may already have persisted STT before this migration. Reuse
    # its text as an editable draft rather than paying for another transcription.
    op.execute(
        "UPDATE sources SET review_state = 'awaiting_review', status = 'awaiting_review', "
        "processing_stage = 'awaiting_review', raw_transcript_text = transcript_text, "
        "raw_utterances = jsonb_build_array(jsonb_build_object('id', 'server-legacy-0', "
        "'personId', null, 'speakerName', '화자 1', 'text', transcript_text, "
        "'startSeconds', 0, 'endSeconds', duration_seconds)), "
        "review_utterances = jsonb_build_array(jsonb_build_object('id', 'server-legacy-0', "
        "'personId', null, 'speakerName', '화자 1', 'text', transcript_text, "
        "'startSeconds', 0, 'endSeconds', duration_seconds)) "
        "WHERE kind = 'meeting' AND transcript_source = 'server' AND status <> 'succeeded' "
        "AND nullif(trim(transcript_text), '') IS NOT NULL"
    )
    op.execute(
        "UPDATE sources SET review_state = 'transcribing' "
        "WHERE kind = 'meeting' AND transcript_source = 'server' AND status <> 'succeeded' "
        "AND nullif(trim(transcript_text), '') IS NULL"
    )
    op.execute(
        "UPDATE sources SET review_state = 'awaiting_review', status = 'awaiting_review', "
        "processing_stage = 'awaiting_review', "
        "review_utterances = CASE WHEN nullif(trim(transcript_text), '') IS NULL THEN '[]'::jsonb "
        "ELSE jsonb_build_array(jsonb_build_object('id', 'legacy-0', 'personId', null, "
        "'speakerName', '화자 1', 'text', transcript_text, "
        "'startSeconds', 0, 'endSeconds', duration_seconds)) END "
        "WHERE kind = 'meeting' AND transcript_source IS DISTINCT FROM 'server' "
        "AND status <> 'succeeded'"
    )


def downgrade() -> None:
    for column in (
        "confirmed_snapshot",
        "confirmed_at",
        "project_id",
        "review_revision",
        "review_state",
        "review_utterances",
        "raw_utterances",
        "raw_transcript_text",
    ):
        op.drop_column("sources", column)
    op.drop_index("workspace_projects_workspace_id_idx", table_name="workspace_projects")
    op.drop_table("workspace_projects")
    op.drop_index("workspace_people_workspace_id_idx", table_name="workspace_people")
    op.drop_table("workspace_people")

"""Project rosters, source associations, person email identity and local provider marker."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609230001"
down_revision = "202609220001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_people", sa.Column("email", sa.String(320)))
    op.add_column("workspace_people", sa.Column("email_normalized", sa.String(320)))
    op.create_index(
        "uq_workspace_people_email_normalized",
        "workspace_people",
        ["workspace_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("email_normalized IS NOT NULL"),
    )
    op.add_column(
        "workspace_projects",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sources",
        sa.Column("association_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "person_id", name="uq_project_members_pair"),
    )
    op.create_index("project_members_workspace_idx", "project_members", ["workspace_id"])
    op.execute("ALTER TABLE project_members ENABLE ROW LEVEL SECURITY")
    op.create_table(
        "source_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("source_id", "project_id", name="uq_source_projects_pair"),
    )
    op.create_index("source_projects_workspace_idx", "source_projects", ["workspace_id"])
    op.execute("ALTER TABLE source_projects ENABLE ROW LEVEL SECURITY")
    op.create_table(
        "source_people",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.CheckConstraint("role IN ('participant', 'author')", name="ck_source_people_role"),
        sa.UniqueConstraint("source_id", "person_id", "role", name="uq_source_people_triple"),
    )
    op.create_index("source_people_workspace_idx", "source_people", ["workspace_id"])
    op.execute("ALTER TABLE source_people ENABLE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO source_projects (id, workspace_id, source_id, project_id, position) "
        "SELECT gen_random_uuid(), workspace_id, id, project_id, 0 "
        "FROM sources WHERE project_id IS NOT NULL"
    )
    op.drop_constraint("ck_provider_credentials_has_secret", "provider_credentials", type_="check")
    op.create_check_constraint(
        "ck_provider_credentials_has_secret",
        "provider_credentials",
        "provider = 'ollama' OR vault_secret_id IS NOT NULL OR encrypted_secret IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_provider_credentials_has_secret", "provider_credentials", type_="check")
    op.create_check_constraint(
        "ck_provider_credentials_has_secret",
        "provider_credentials",
        "vault_secret_id IS NOT NULL OR encrypted_secret IS NOT NULL",
    )
    for table, index in (
        ("source_people", "source_people_workspace_idx"),
        ("source_projects", "source_projects_workspace_idx"),
        ("project_members", "project_members_workspace_idx"),
    ):
        op.drop_index(index, table_name=table)
        op.drop_table(table)
    op.drop_column("sources", "association_revision")
    op.drop_column("workspace_projects", "revision")
    op.drop_index("uq_workspace_people_email_normalized", table_name="workspace_people")
    op.drop_column("workspace_people", "email_normalized")
    op.drop_column("workspace_people", "email")

"""Separate account and workspace provider credentials.

Revision ID: 202609280001
Revises: 202609270001
"""

import sqlalchemy as sa
from alembic import op

revision = "202609280001"
down_revision = "202609270001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Since 202609250001 credentials have been account-owned even though the
    # compatibility column retained the workspace where they were first made.
    op.execute("UPDATE provider_credentials SET workspace_id = NULL")
    op.drop_constraint(
        "provider_credentials_workspace_id_fkey", "provider_credentials", type_="foreignkey"
    )
    op.create_foreign_key(
        "provider_credentials_workspace_id_fkey",
        "provider_credentials",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_provider_credential_owner_label", "provider_credentials", type_="unique")
    op.drop_index("provider_credentials_one_default_idx", table_name="provider_credentials")
    op.create_index(
        "provider_credentials_account_label_idx",
        "provider_credentials",
        ["owner_id", "provider", "label"],
        unique=True,
        postgresql_where=sa.text("workspace_id is null"),
    )
    op.create_index(
        "provider_credentials_workspace_label_idx",
        "provider_credentials",
        ["workspace_id", "provider", "label"],
        unique=True,
        postgresql_where=sa.text("workspace_id is not null"),
    )
    op.create_index(
        "provider_credentials_account_default_idx",
        "provider_credentials",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default and workspace_id is null"),
    )
    op.create_index(
        "provider_credentials_workspace_default_idx",
        "provider_credentials",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default and workspace_id is not null"),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM provider_credentials WHERE workspace_id IS NOT NULL")
        )
        .scalar_one()
    ):
        raise RuntimeError("Cannot merge workspace credentials back into account scope")
    op.drop_index("provider_credentials_workspace_default_idx", table_name="provider_credentials")
    op.drop_index("provider_credentials_account_default_idx", table_name="provider_credentials")
    op.drop_index("provider_credentials_workspace_label_idx", table_name="provider_credentials")
    op.drop_index("provider_credentials_account_label_idx", table_name="provider_credentials")
    op.create_unique_constraint(
        "uq_provider_credential_owner_label",
        "provider_credentials",
        ["owner_id", "provider", "label"],
    )
    op.create_index(
        "provider_credentials_one_default_idx",
        "provider_credentials",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.drop_constraint(
        "provider_credentials_workspace_id_fkey", "provider_credentials", type_="foreignkey"
    )
    op.create_foreign_key(
        "provider_credentials_workspace_id_fkey",
        "provider_credentials",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

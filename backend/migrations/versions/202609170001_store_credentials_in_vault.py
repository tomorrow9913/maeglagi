"""Store provider credentials in Supabase Vault.

Revision ID: 202609170001
Revises: 202609160001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609170001"
down_revision = "202609160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create extension if not exists supabase_vault cascade")
    op.add_column(
        "provider_credentials",
        sa.Column("vault_secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("provider_credentials", "encrypted_secret", nullable=True)
    op.create_check_constraint(
        "ck_provider_credentials_has_secret",
        "provider_credentials",
        "vault_secret_id is not null or encrypted_secret is not null",
    )
    op.execute("revoke all on vault.decrypted_secrets from anon, authenticated")


def downgrade() -> None:
    op.drop_constraint("ck_provider_credentials_has_secret", "provider_credentials", type_="check")
    # Vault plaintext is deliberately never copied back into the application table.
    # Refuse a downgrade that would otherwise require deleting credentials.
    op.execute(
        """
        do $$
        begin
          if exists (select 1 from provider_credentials where encrypted_secret is null) then
            raise exception 'cannot downgrade while Vault-only credentials exist';
          end if;
        end $$
        """
    )
    op.drop_column("provider_credentials", "vault_secret_id")
    op.alter_column("provider_credentials", "encrypted_secret", nullable=False)

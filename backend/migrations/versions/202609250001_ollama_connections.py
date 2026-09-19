"""Move provider credentials to account scope and store Ollama server addresses.

Revision ID: 202609250001
Revises: 202609240001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609250001"
down_revision = "202609240001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_credentials", sa.Column("base_url", sa.Text(), nullable=True))
    op.alter_column(
        "provider_credentials", "key_hint", existing_type=sa.String(8), type_=sa.String(16)
    )
    # Pin each old workspace choice to the credential its legacy resolver preferred:
    # an active workspace default first, then the oldest active credential. This
    # preserves workspace preference when account-wide defaults are consolidated.
    # The provider's model availability cannot be queried during a migration.
    op.execute("""
        DO $$
        DECLARE w record; choice record; settings jsonb; matching_id uuid;
        BEGIN
          FOR w IN SELECT id, model_settings FROM workspaces LOOP
            settings := w.model_settings;
            FOR choice IN SELECT key, value FROM jsonb_each(settings) LOOP
              IF jsonb_typeof(choice.value) = 'object'
                 AND choice.value ? 'provider'
                 AND NOT choice.value ? 'credentialId' THEN
                SELECT id INTO matching_id
                FROM provider_credentials
                WHERE workspace_id = w.id
                  AND provider = choice.value->>'provider'
                  AND status = 'active'
                ORDER BY is_default DESC, created_at, id
                LIMIT 1;
                IF matching_id IS NOT NULL THEN
                  settings := jsonb_set(
                    settings, ARRAY[choice.key, 'credentialId'], to_jsonb(matching_id::text)
                  );
                END IF;
              END IF;
            END LOOP;
            IF settings IS DISTINCT FROM w.model_settings THEN
              UPDATE workspaces SET model_settings = settings WHERE id = w.id;
            END IF;
          END LOOP;
        END $$
    """)

    # Store original labels so a rollback can restore every row exactly. No
    # credential or Vault secret is merged or discarded.
    op.create_table(
        "provider_credential_migration_labels",
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_credentials.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("original_label", sa.String(80), nullable=False),
        sa.Column("was_default", sa.Boolean(), nullable=False),
        sa.Column("original_key_hint", sa.String(16), nullable=False),
    )
    op.execute("ALTER TABLE provider_credential_migration_labels ENABLE ROW LEVEL SECURITY")
    op.execute("""
        INSERT INTO provider_credential_migration_labels
          (credential_id, original_label, was_default, original_key_hint)
        SELECT id, label, is_default, key_hint FROM provider_credentials
    """)
    op.execute("""
        UPDATE provider_credentials
        SET key_hint = CASE WHEN vault_secret_id IS NULL THEN 'none' ELSE 'configured' END
        WHERE provider = 'ollama'
    """)
    op.execute("""
        DO $$
        DECLARE row_to_rename record; candidate text; attempt integer;
        BEGIN
          FOR row_to_rename IN
            SELECT id, owner_id, provider, label FROM (
              SELECT id, owner_id, provider, label,
                     row_number() OVER (
                       PARTITION BY owner_id, provider, label ORDER BY created_at, id
                     ) AS position
              FROM provider_credentials
            ) ranked WHERE position > 1 ORDER BY owner_id, provider, label, id
          LOOP
            candidate := left(row_to_rename.label, 40) || ' #' || row_to_rename.id::text;
            attempt := 1;
            WHILE EXISTS (
              SELECT 1 FROM provider_credentials
              WHERE owner_id = row_to_rename.owner_id
                AND provider = row_to_rename.provider
                AND label = candidate AND id <> row_to_rename.id
            ) LOOP
              candidate := left(row_to_rename.label, 30) || ' #'
                           || row_to_rename.id::text || '-' || attempt::text;
              attempt := attempt + 1;
            END LOOP;
            UPDATE provider_credentials SET label = candidate WHERE id = row_to_rename.id;
          END LOOP;
        END $$
    """)
    op.drop_constraint("uq_provider_credential_label", "provider_credentials", type_="unique")
    op.create_unique_constraint(
        "uq_provider_credential_owner_label",
        "provider_credentials",
        ["owner_id", "provider", "label"],
    )
    op.drop_index("provider_credentials_one_default_idx", table_name="provider_credentials")
    op.execute("""
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY owner_id ORDER BY created_at, id
          ) AS position
          FROM provider_credentials WHERE is_default
        )
        UPDATE provider_credentials AS c SET is_default = false
        FROM ranked WHERE c.id = ranked.id AND ranked.position > 1
    """)
    op.create_index(
        "provider_credentials_one_default_idx",
        "provider_credentials",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index("provider_credentials_owner_id_idx", "provider_credentials", ["owner_id"])
    op.drop_constraint(
        "provider_credentials_workspace_id_fkey", "provider_credentials", type_="foreignkey"
    )
    op.alter_column(
        "provider_credentials", "workspace_id", existing_type=postgresql.UUID(), nullable=True
    )
    op.create_foreign_key(
        "provider_credentials_workspace_id_fkey",
        "provider_credentials",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    connection = op.get_bind()
    missing_origin = connection.execute(
        sa.text("SELECT count(*) FROM provider_credentials WHERE workspace_id IS NULL")
    ).scalar_one()
    if missing_origin:
        raise RuntimeError("Cannot roll back account credentials without a legacy workspace")
    long_new_hint = connection.execute(
        sa.text("""
        SELECT count(*) FROM provider_credentials AS c
        LEFT JOIN provider_credential_migration_labels AS original
          ON original.credential_id = c.id
        WHERE original.credential_id IS NULL AND length(c.key_hint) > 8
    """)
    ).scalar_one()
    if long_new_hint:
        raise RuntimeError("Cannot roll back new credential hints into the legacy schema")
    op.drop_constraint(
        "provider_credentials_workspace_id_fkey", "provider_credentials", type_="foreignkey"
    )
    op.alter_column(
        "provider_credentials", "workspace_id", existing_type=postgresql.UUID(), nullable=False
    )
    op.create_foreign_key(
        "provider_credentials_workspace_id_fkey",
        "provider_credentials",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("provider_credentials_owner_id_idx", table_name="provider_credentials")
    op.drop_index("provider_credentials_one_default_idx", table_name="provider_credentials")
    op.create_index(
        "provider_credentials_one_default_idx",
        "provider_credentials",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.drop_constraint("uq_provider_credential_owner_label", "provider_credentials", type_="unique")
    op.execute("""
        UPDATE provider_credentials AS c
        SET label = original.original_label,
            is_default = original.was_default,
            key_hint = original.original_key_hint
        FROM provider_credential_migration_labels AS original
        WHERE c.id = original.credential_id
    """)
    op.drop_table("provider_credential_migration_labels")
    op.create_unique_constraint(
        "uq_provider_credential_label",
        "provider_credentials",
        ["workspace_id", "provider", "label"],
    )
    # credentialId is harmless in legacy workspace JSON and preserves the user's choice.
    op.alter_column(
        "provider_credentials", "key_hint", existing_type=sa.String(16), type_=sa.String(8)
    )
    op.drop_column("provider_credentials", "base_url")

"""Exercise the account-credential revision in a disposable local database."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest


def test_account_migration_preserves_workspace_choices_and_rolls_back() -> None:
    source_url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not source_url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to a local PostgreSQL instance")
    parsed = urlsplit(source_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Migration test requires a loopback PostgreSQL host")

    # Migrate only the revision under test; never alter the shared test database.
    database_name = f"migration_{uuid4().hex}"
    temporary_url = urlunsplit(parsed._replace(path=f"/{database_name}"))
    admin_dsn = source_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    temporary_dsn = temporary_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": temporary_url}

    def migrate(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    async def exercise() -> None:
        admin = await asyncpg.connect(admin_dsn)
        try:
            await admin.execute(f'CREATE DATABASE "{database_name}"')
            conn = await asyncpg.connect(temporary_dsn)
            try:
                # Minimal schema at revision 202609240001, with its named constraints.
                await conn.execute("""
                    CREATE TABLE workspaces (
                      id uuid PRIMARY KEY, owner_id uuid NOT NULL,
                      name varchar(120) NOT NULL, model_settings jsonb NOT NULL,
                      created_at timestamptz NOT NULL
                    );
                    CREATE TABLE provider_credentials (
                      id uuid PRIMARY KEY,
                      workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                      owner_id uuid NOT NULL, provider varchar(40) NOT NULL,
                      label varchar(80) NOT NULL, vault_secret_id uuid,
                      encrypted_secret text, key_hint varchar(8) NOT NULL,
                      status varchar(20) NOT NULL, is_default boolean NOT NULL,
                      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
                      CONSTRAINT uq_provider_credential_label
                        UNIQUE (workspace_id, provider, label),
                      CONSTRAINT ck_provider_credentials_has_secret CHECK (
                        provider = 'ollama' OR vault_secret_id IS NOT NULL
                        OR encrypted_secret IS NOT NULL
                      )
                    );
                    CREATE UNIQUE INDEX provider_credentials_one_default_idx
                      ON provider_credentials (workspace_id) WHERE is_default;
                    CREATE INDEX provider_credentials_workspace_id_idx
                      ON provider_credentials (workspace_id);
                """)
                migrate("stamp", "202609240001")
                owner = uuid4()
                first_ws, second_ws, third_ws = (uuid4() for _ in range(3))
                # Workspace one's newer default must remain its choice when
                # workspace two's older default becomes the account default.
                first_old, first_default, second_default, third_old, third_new = (
                    uuid4() for _ in range(5)
                )
                keyed_id, secret_id = uuid4(), uuid4()
                selected = json.dumps(
                    {"answer": {"provider": "ollama", "model": "same:latest"}}
                )
                for workspace_id, name in (
                    (first_ws, "first"),
                    (second_ws, "second"),
                    (third_ws, "third"),
                ):
                    await conn.execute(
                        "INSERT INTO workspaces (id,owner_id,name,model_settings,created_at) "
                        "VALUES ($1,$2,$3,$4::jsonb,now())",
                        workspace_id, owner, name, selected,
                    )
                for credential_id, workspace_id, label, is_default, day in (
                    (first_old, first_ws, "other", False, 1),
                    (first_default, first_ws, "same label", True, 3),
                    (second_default, second_ws, "same label", True, 2),
                    (third_old, third_ws, "older", False, 4),
                    (third_new, third_ws, "newer", False, 5),
                ):
                    await conn.execute(
                        "INSERT INTO provider_credentials "
                        "(id,workspace_id,owner_id,provider,label,key_hint,is_default,status,"
                        "created_at,updated_at) VALUES "
                        "($1,$2,$3,'ollama',$4,'local',$5,'active',"
                        "'2026-09-01'::timestamptz + $6 * interval '1 day',now())",
                        credential_id, workspace_id, owner, label, is_default, day,
                    )
                await conn.execute(
                    "INSERT INTO provider_credentials "
                    "(id,workspace_id,owner_id,provider,label,key_hint,is_default,status,"
                    "vault_secret_id,created_at,updated_at) "
                    "VALUES ($1,$2,$3,'openai','api','ABCD',false,'active',$4,now(),now())",
                    keyed_id, first_ws, owner, secret_id,
                )
                migrate("upgrade", "head")
                rows = await conn.fetch(
                    "SELECT id,label,is_default FROM provider_credentials "
                    "WHERE owner_id=$1 AND provider='ollama'", owner,
                )
                assert len(rows) == 5
                assert len({row["label"] for row in rows}) == 5
                assert sum(row["is_default"] for row in rows) == 1
                for workspace_id, expected_id in (
                    (first_ws, first_default),
                    (second_ws, second_default),
                    (third_ws, third_old),
                ):
                    assert await conn.fetchval(
                        "SELECT model_settings->'answer'->>'credentialId' "
                        "FROM workspaces WHERE id=$1", workspace_id,
                    ) == str(expected_id)
                assert await conn.fetchval(
                    "SELECT vault_secret_id FROM provider_credentials WHERE id=$1", keyed_id
                ) == secret_id
                migrate("downgrade", "202609240001")
                restored = await conn.fetch(
                    "SELECT id,label,is_default FROM provider_credentials "
                    "WHERE owner_id=$1 AND provider='ollama'", owner,
                )
                by_id = {row["id"]: row for row in restored}
                assert by_id[first_default]["label"] == "same label"
                assert by_id[second_default]["label"] == "same label"
                assert by_id[first_default]["is_default"]
                assert by_id[second_default]["is_default"]
                assert await conn.fetchval(
                    "SELECT vault_secret_id FROM provider_credentials WHERE id=$1", keyed_id
                ) == secret_id
            finally:
                await conn.close()
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            await admin.close()

    asyncio.run(exercise())

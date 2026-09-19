from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.credentials import (
    CredentialUnavailableError,
    SupabaseCredentialVault,
    resolve_credential_secret,
)


@pytest.mark.asyncio
async def test_vault_create_uses_bound_parameters_and_returns_secret_id() -> None:
    secret_id = uuid4()
    result = SimpleNamespace(scalar_one=lambda: secret_id)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    stored_id = await SupabaseCredentialVault().create(
        session,
        secret="sk-test-provider-secret",
        credential_id=uuid4(),
        workspace_id=uuid4(),
        provider="openai",
    )

    assert stored_id == secret_id
    statement, parameters = session.execute.await_args.args
    assert ":secret" in str(statement)
    assert "sk-test-provider-secret" not in str(statement)
    assert parameters["secret"] == "sk-test-provider-secret"


@pytest.mark.asyncio
async def test_vault_delete_targets_only_the_given_secret_id() -> None:
    secret_id = uuid4()
    session = SimpleNamespace(execute=AsyncMock())

    await SupabaseCredentialVault().delete(session, secret_id=secret_id)

    statement, parameters = session.execute.await_args.args
    assert str(statement) == "delete from vault.secrets where id = :secret_id"
    assert parameters == {"secret_id": secret_id}


@pytest.mark.asyncio
async def test_resolver_reads_vault_secret_by_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_id = uuid4()
    session = SimpleNamespace()
    reveal = AsyncMock(return_value="sk-secret")
    monkeypatch.setattr("app.core.credentials.credential_vault.reveal", reveal)

    secret = await resolve_credential_secret(
        session, SimpleNamespace(vault_secret_id=secret_id, encrypted_secret=None)
    )

    assert secret == "sk-secret"
    reveal.assert_awaited_once_with(session, secret_id=secret_id)


@pytest.mark.asyncio
async def test_resolver_rejects_credential_without_secret() -> None:
    with pytest.raises(CredentialUnavailableError):
        await resolve_credential_secret(
            SimpleNamespace(), SimpleNamespace(vault_secret_id=None, encrypted_secret=None)
        )

import importlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.workspaces.application.account_deletion import (
    AccountDeletionError,
    delete_account_data,
)


def test_delete_account_requires_authentication() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="public-key",
    )
    try:
        response = TestClient(app).request(
            "DELETE", "/api/v1/auth/me", json={"confirmation": "계정 탈퇴"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


def test_delete_account_uses_authenticated_identity(monkeypatch) -> None:
    owner_id = uuid4()
    deletion = AsyncMock()
    monkeypatch.setattr(
        importlib.import_module("app.api.auth.router"), "delete_account_data", deletion
    )
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=owner_id)
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    try:
        response = TestClient(app).request(
            "DELETE", "/api/v1/auth/me", json={"confirmation": "계정 탈퇴"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 204
    assert deletion.await_args.args[0] == owner_id


def test_delete_account_requires_exact_confirmation(monkeypatch) -> None:
    owner_id = uuid4()
    deletion = AsyncMock()
    monkeypatch.setattr(
        importlib.import_module("app.api.auth.router"), "delete_account_data", deletion
    )
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=owner_id)
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    try:
        response = TestClient(app).request(
            "DELETE", "/api/v1/auth/me", json={"confirmation": "삭제"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    deletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_deletion_removes_files_and_identity(monkeypatch) -> None:
    owner_id, workspace_id, secret_id = uuid4(), uuid4(), uuid4()
    session = AsyncMock()
    session.exec.side_effect = [
        MagicMock(all=lambda: [workspace_id]),
        MagicMock(all=lambda: [secret_id]),
    ]
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [
        f"{owner_id}/{workspace_id}/recording.webm"
    ]
    graph = AsyncMock()
    requests = []

    def responder(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(responder), **kwargs),
    )
    vault_delete = AsyncMock()
    monkeypatch.setattr(
        "app.modules.workspaces.application.account_deletion.credential_vault.delete", vault_delete
    )
    await delete_account_data(
        owner_id,
        session,
        Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="private"),
        graph,
    )
    assert [request.url.path for request in requests] == [
        "/storage/v1/object/sources",
        f"/auth/v1/admin/users/{owner_id}",
    ]
    assert requests[0].method == "DELETE"
    assert requests[0].headers["authorization"] == "Bearer private"
    graph.execute.assert_awaited_once()
    vault_delete.assert_awaited_once_with(session, secret_id=secret_id)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_account_deletion_failure_does_not_delete_identity(monkeypatch) -> None:
    owner_id = uuid4()
    session = AsyncMock()
    session.exec.side_effect = [MagicMock(all=lambda: []), MagicMock(all=lambda: [])]
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [f"{owner_id}/file"]
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(500)), **kwargs
        ),
    )
    with pytest.raises(AccountDeletionError):
        await delete_account_data(
            owner_id,
            session,
            Settings(
                supabase_url="https://example.supabase.co", supabase_service_role_key="private"
            ),
            None,
        )
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_failure_rolls_back_vault_deletion(monkeypatch) -> None:
    owner_id, secret_id = uuid4(), uuid4()
    session = AsyncMock()
    session.exec.side_effect = [MagicMock(all=lambda: []), MagicMock(all=lambda: [secret_id])]
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.execute.return_value.scalar_one_or_none.return_value = None
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(500)), **kwargs
        ),
    )
    vault_delete = AsyncMock()
    monkeypatch.setattr(
        "app.modules.workspaces.application.account_deletion.credential_vault.delete", vault_delete
    )
    with pytest.raises(AccountDeletionError):
        await delete_account_data(
            owner_id,
            session,
            Settings(
                supabase_url="https://example.supabase.co", supabase_service_role_key="private"
            ),
            None,
        )
    vault_delete.assert_awaited_once_with(session, secret_id=secret_id)
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()

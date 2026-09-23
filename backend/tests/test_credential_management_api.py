import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.workspaces import credentials as routes
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import app
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace


class CredentialSession:
    def __init__(self, workspace, credentials):
        self.workspace = workspace
        self.credentials = credentials
        self.added = []
        self.deleted = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def get(self, model, item_id, **kwargs):
        if model is Workspace:
            return self.workspace if item_id == self.workspace.id else None
        return next((c for c in self.credentials if c.id == item_id), None)

    async def exec(self, statement):
        # The workspace and owner checks in the handlers are the authorization boundary.
        return SimpleNamespace(
            all=lambda: list(self.credentials),
            first=lambda: next((c for c in self.credentials if c.is_default), None),
        )

    def add(self, item):
        self.added.append(item)
        if isinstance(item, ProviderCredential) and item not in self.credentials:
            self.credentials.append(item)

    async def delete(self, item):
        self.deleted.append(item)
        self.credentials.remove(item)


@pytest.fixture
def setup_api(monkeypatch):
    owner = uuid4()
    settings = {"answer": {"provider": "openai", "model": "gpt-4o-mini"}}
    workspace = Workspace(owner_id=owner, name="test", model_settings=settings)
    first = ProviderCredential(
        workspace_id=workspace.id,
        owner_id=owner,
        provider="openai",
        label="primary",
        key_hint="0001",
        is_default=True,
        vault_secret_id=uuid4(),
    )
    second = ProviderCredential(
        workspace_id=workspace.id,
        owner_id=owner,
        provider="openai",
        label="backup",
        key_hint="0002",
        vault_secret_id=uuid4(),
    )
    session = CredentialSession(workspace, [first, second])
    vault_update = AsyncMock()
    vault_delete = AsyncMock()
    vault_create = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(routes.credential_vault, "update", vault_update)
    monkeypatch.setattr(routes.credential_vault, "delete", vault_delete, raising=False)
    monkeypatch.setattr(routes, "store_credential_secret", vault_create)
    monkeypatch.setattr(
        routes, "validate_provider_credential", AsyncMock(return_value=(True, "ok"))
    )

    async def get_test_session():
        yield session

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(owner), metadata={})
    app.dependency_overrides[get_session] = get_test_session
    try:
        yield SimpleNamespace(
            client=TestClient(app),
            workspace=workspace,
            credentials=session.credentials,
            first=first,
            second=second,
            session=session,
            update=vault_update,
            delete=vault_delete,
            create=vault_create,
        )
    finally:
        app.dependency_overrides.clear()


def test_add_and_rotate_are_isolated_from_default_and_models(setup_api):
    case = setup_api
    path = f"/api/v1/workspaces/{case.workspace.id}/provider-credentials"
    settings = case.workspace.model_settings.copy()
    added = case.client.post(
        path,
        json={
            "provider": "anthropic",
            "label": "research",
            "apiKey": "secret-new-1234",
        },
    )
    assert added.status_code == 201
    assert added.json()["isDefault"] is False
    assert "secret-new" not in added.text
    assert case.first.is_default is True
    assert case.workspace.model_settings == settings
    assert (
        case.client.post(
            path,
            json={
                "provider": "anthropic",
                "label": "research",
                "apiKey": "duplicate",
            },
        ).status_code
        == 409
    )
    rotated = case.client.put(f"{path}/{case.second.id}", json={"apiKey": "rotated-9999"})
    assert rotated.status_code == 200
    assert rotated.json()["keyHint"] == "9999"
    assert rotated.json()["isDefault"] is False
    assert "rotated" not in rotated.text
    case.update.assert_awaited_once_with(
        case.session, secret_id=case.second.vault_secret_id, secret="rotated-9999"
    )
    assert case.first.is_default is True
    assert case.workspace.model_settings == settings


def test_default_transition_and_deletion_rules(setup_api):
    case = setup_api
    path = f"/api/v1/workspaces/{case.workspace.id}/provider-credentials"
    settings = case.workspace.model_settings.copy()
    assert case.client.delete(f"{path}/{case.first.id}").status_code == 409
    chosen = case.client.put(f"{path}/{case.second.id}/default")
    assert chosen.status_code == 200
    assert chosen.json()["isDefault"] is True
    assert case.first.is_default is False
    assert case.session.flush.await_count == 1
    deleted = case.client.delete(f"{path}/{case.first.id}")
    assert deleted.status_code == 204
    case.delete.assert_awaited_once_with(case.session, secret_id=case.first.vault_secret_id)
    assert case.first not in case.credentials
    assert case.workspace.model_settings == settings
    assert case.client.delete(f"{path}/{case.second.id}").status_code == 409
    assert case.second in case.credentials
    assert case.delete.await_count == 1
    case.workspace.model_settings = {}
    assert case.client.delete(f"{path}/{case.second.id}").status_code == 204
    assert case.credentials == []
    assert case.client.get(f"/api/v1/workspaces/{case.workspace.id}/llm-key").json() is None


def test_workspace_credential_cannot_be_mutated_through_another_workspace(setup_api):
    case = setup_api
    path = f"/api/v1/workspaces/{case.workspace.id}/provider-credentials"
    other = ProviderCredential(
        workspace_id=uuid4(),
        owner_id=case.workspace.owner_id,
        provider="openai",
        label="other",
        key_hint="0000",
        vault_secret_id=uuid4(),
    )
    case.credentials.append(other)
    assert case.client.put(f"{path}/{other.id}", json={"apiKey": "private"}).status_code == 404
    assert case.client.put(f"{path}/{other.id}/default").status_code == 404
    assert case.update.await_count == 0
    case.workspace.owner_id = uuid4()
    assert (
        case.client.post(
            path,
            json={
                "provider": "openai",
                "label": "new",
                "apiKey": "private",
            },
        ).status_code
        == 404
    )
    assert case.create.await_count == 0


def test_invalid_provider_key_is_rejected_before_vault_write(setup_api, monkeypatch):
    case = setup_api
    validator = AsyncMock(return_value=(False, "invalid provider key"))
    monkeypatch.setattr(routes, "validate_provider_credential", validator)
    path = f"/api/v1/workspaces/{case.workspace.id}/provider-credentials"
    added = case.client.post(
        path,
        json={
            "provider": "unknown",
            "label": "unknown",
            "apiKey": "private",
        },
    )
    rotated = case.client.put(f"{path}/{case.second.id}", json={"apiKey": "private"})
    assert added.status_code == 422
    assert rotated.status_code == 422
    assert case.create.await_count == 0
    assert case.update.await_count == 0
    assert case.second.key_hint == "0002"


def test_changing_ollama_endpoint_requires_recent_login_and_a_new_key(setup_api, monkeypatch):
    case = setup_api
    case.second.provider = "ollama"
    case.second.base_url = "https://old-ollama.example"
    path = f"/api/v1/workspaces/{case.workspace.id}/provider-credentials/{case.second.id}"
    reveal = AsyncMock(return_value="stored-secret")
    monkeypatch.setattr(routes, "resolve_credential_secret", reveal)

    stale = case.client.put(
        path,
        json={"baseUrl": "https://new-ollama.example", "apiKey": "new-secret"},
    )
    assert stale.status_code == 403
    assert stale.json()["detail"] == routes.RECENT_AUTH_REQUIRED
    reveal.assert_not_awaited()

    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=str(case.workspace.owner_id),
        last_sign_in_at=datetime.now(UTC),
        metadata={},
    )
    missing_key = case.client.put(path, json={"baseUrl": "https://new-ollama.example"})
    assert missing_key.status_code == 422
    assert missing_key.json()["detail"] == routes.OLLAMA_ENDPOINT_KEY_REQUIRED
    reveal.assert_not_awaited()

    changed = case.client.put(
        path,
        json={"baseUrl": "https://new-ollama.example", "apiKey": "new-secret"},
    )
    assert changed.status_code == 200
    assert case.second.base_url == "https://new-ollama.example"
    reveal.assert_not_awaited()


def test_legacy_default_route_does_not_reveal_ollama_key_before_endpoint_checks(
    setup_api, monkeypatch
):
    case = setup_api
    case.second.provider = "ollama"
    case.second.base_url = "https://old-ollama.example"
    reveal = AsyncMock(return_value="stored-secret")
    monkeypatch.setattr(routes, "resolve_credential_secret", reveal)
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=str(case.workspace.owner_id),
        last_sign_in_at=datetime.now(UTC),
        metadata={},
    )

    response = case.client.put(
        f"/api/v1/workspaces/{case.workspace.id}/llm-key",
        json={
            "provider": "ollama",
            "label": case.second.label,
            "baseUrl": "https://new-ollama.example",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == routes.OLLAMA_ENDPOINT_KEY_REQUIRED
    reveal.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_adds_of_same_label_serialize_to_conflict(monkeypatch):
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="test", model_settings={})
    credentials = []
    row_lock = asyncio.Lock()
    first_storing = asyncio.Event()
    finish_first = asyncio.Event()
    user = AuthUser(id=str(owner), metadata={})

    class LockedSession(CredentialSession):
        def __init__(self):
            super().__init__(workspace, credentials)
            self.has_lock = False
            self.commit = self._commit

        async def get(self, model, item_id, **kwargs):
            if model is Workspace and kwargs.get("with_for_update"):
                await row_lock.acquire()
                self.has_lock = True
                assert kwargs["populate_existing"] is True
            return await super().get(model, item_id, **kwargs)

        async def _commit(self):
            if self.has_lock:
                self.has_lock = False
                row_lock.release()

    async def store_first_then_release(*args, **kwargs):
        first_storing.set()
        await finish_first.wait()
        return uuid4()

    monkeypatch.setattr(
        routes, "validate_provider_credential", AsyncMock(return_value=(True, "ok"))
    )
    monkeypatch.setattr(routes, "store_credential_secret", store_first_then_release)
    first_session = LockedSession()
    second_session = LockedSession()
    body = routes.CredentialInput(provider="openai", apiKey="private", label="same")
    first_task = asyncio.create_task(routes.add_credential(workspace.id, body, user, first_session))
    await first_storing.wait()
    second_task = asyncio.create_task(
        routes.add_credential(workspace.id, body, user, second_session)
    )
    await asyncio.sleep(0)
    assert not second_task.done()
    finish_first.set()
    first = await first_task
    try:
        with pytest.raises(HTTPException) as conflict:
            await second_task
        assert conflict.value.status_code == 409
    finally:
        if second_session.has_lock:
            row_lock.release()
    assert first.label == "same"
    assert len(credentials) == 1

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.workspaces import credentials as routes
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import app
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace


@pytest.mark.parametrize("configured", [False, True])
def test_list_and_rotate_credentials_preserve_other_providers_and_models(monkeypatch, configured):
    owner = uuid4()
    chosen = (
        {"embedding": {"provider": "openai", "model": "text-embedding-3-small"}}
        if configured
        else {}
    )
    workspace = Workspace(owner_id=owner, name="test", model_settings=chosen)
    credentials = [
        ProviderCredential(
            workspace_id=workspace.id,
            owner_id=owner,
            provider=provider,
            label="기본",
            key_hint="old1",
            is_default=index == 0,
            vault_secret_id=uuid4(),
        )
        for index, provider in enumerate(("openai", "anthropic"))
    ]
    session = SimpleNamespace(
        get=AsyncMock(return_value=workspace),
        exec=AsyncMock(return_value=SimpleNamespace(all=lambda: credentials)),
        add=lambda _: None,
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    update = AsyncMock()
    monkeypatch.setattr(routes.credential_vault, "update", update)
    monkeypatch.setattr(
        routes, "validate_provider_credential", AsyncMock(return_value=(True, "ok"))
    )

    async def get_test_session():
        yield session

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(owner), metadata={})
    app.dependency_overrides[get_session] = get_test_session
    try:
        client = TestClient(app)
        path = f"/api/v1/workspaces/{workspace.id}"
        listed = client.get(path + "/provider-credentials")
        assert listed.status_code == 200
        assert [c["provider"] for c in listed.json()] == ["openai", "anthropic"]
        assert all(
            set(c)
            == {"id", "provider", "label", "baseUrl", "keyHint", "status", "isDefault", "updatedAt"}
            for c in listed.json()
        )
        original_secret = credentials[0].vault_secret_id
        rotated = client.put(
            path + "/llm-key",
            json={
                "provider": "anthropic",
                "label": "기본",
                "apiKey": "new-private-key-9876",
            },
        )
        assert rotated.status_code == 200
        assert rotated.json()["id"] == str(credentials[1].id)
        assert rotated.json()["keyHint"] == "9876"
        assert rotated.json()["isDefault"] is True
        assert credentials[0].is_default is False
        assert credentials[0].vault_secret_id == original_secret
        assert workspace.model_settings == chosen
        update.assert_awaited_once_with(
            session, secret_id=credentials[1].vault_secret_id, secret="new-private-key-9876"
        )
        assert "new-private-key" not in rotated.text
        workspace.owner_id = uuid4()
        assert client.get(path + "/provider-credentials").status_code == 404
        assert (
            client.put(
                path + "/llm-key", json={"provider": "anthropic", "apiKey": "never-stored"}
            ).status_code
            == 404
        )
        assert update.await_count == 1
    finally:
        app.dependency_overrides.clear()

import importlib
from collections.abc import AsyncIterator, Iterator
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.application.provider import ModelInfo
from app.modules.context_engine.infrastructure.provider_registry import provider_registry
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

ai_router = importlib.import_module("app.api.ai.router")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id="00000000-0000-0000-0000-000000000001", metadata={}
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_catalog_lists_every_registered_provider_with_its_real_capabilities(
    client: TestClient,
) -> None:
    body = client.get("/api/v1/ai/providers").json()

    assert [item["id"] for item in body] == [a.id for a in provider_registry.all()]
    by_id = {item["id"]: item for item in body}
    assert {"embedding", "structuredOutput", "transcription"} <= set(
        by_id["openai"]["capabilities"]
    )
    # Anthropic and NVIDIA cannot index or extract, which the UI must be able to tell users.
    assert "embedding" not in by_id["anthropic"]["capabilities"]
    assert "structuredOutput" not in by_id["nvidia"]["capabilities"]


def test_catalog_uses_the_same_shape_as_the_workspace_catalog(client: TestClient) -> None:
    item = client.get("/api/v1/ai/providers").json()[0]

    assert set(item) == {
        "id",
        "displayName",
        "capabilities",
        "configured",
        "authMode",
        "models",
        "defaultModels",
    }
    assert item["configured"] is False
    assert item["models"] == []


def test_catalog_requires_a_signed_in_user() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        supabase_url="https://example.supabase.co", supabase_publishable_key="sb_publishable_test"
    )
    try:
        response = TestClient(app).get("/api/v1/ai/providers")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_the_catalog_gives_each_providers_default_models_so_they_show_as_soon_as_it_is_picked(
    client: TestClient,
) -> None:
    by_id = {item["id"]: item for item in client.get("/api/v1/ai/providers").json()}

    assert by_id["openai"]["defaultModels"]["embedding"] == "text-embedding-3-small"
    assert set(by_id["openai"]["defaultModels"]) == {
        "answer",
        "extraction",
        "embedding",
        "transcription",
    }
    # A provider that cannot embed has no embedding default; the UI shows nothing for that job.
    assert "embedding" not in by_id["anthropic"]["defaultModels"]
    assert by_id["anthropic"]["defaultModels"]["answer"]


def test_operators_can_change_the_defaults_without_touching_code(client: TestClient) -> None:
    from app.core.config import Settings, get_settings
    from app.main import app as application

    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        provider_default_models={"openai": {"answer": "some-newer-model"}},
    )

    item = next(i for i in client.get("/api/v1/ai/providers").json() if i["id"] == "openai")

    assert item["defaultModels"] == {"answer": "some-newer-model"}


def test_workspace_catalog_includes_defaults_and_excludes_retired_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="catalog")
    credential = ProviderCredential(
        workspace_id=workspace.id, owner_id=owner, provider="openai", key_hint="1234"
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=workspace),
        exec=AsyncMock(return_value=SimpleNamespace(all=lambda: [credential])),
    )

    class Adapter:
        id = "openai"
        display_name = "OpenAI"
        capabilities = ("chat", "models")

        async def list_model_infos(self, api_key: str) -> list[ModelInfo]:
            return [
                ModelInfo(id="gpt-live"),
                ModelInfo(id="gpt-retired", shutdown_date=date(2020, 1, 1)),
            ]

    async def test_session() -> AsyncIterator[object]:
        yield session

    async def secret(*args: object) -> str:
        return "test-key"

    monkeypatch.setattr(ai_router.provider_registry, "all", lambda: [Adapter()])
    monkeypatch.setattr(ai_router, "resolve_credential_secret", secret)
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(owner), metadata={})
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, provider_default_models={"openai": {"answer": "gpt-live"}}
    )
    try:
        response = TestClient(app).get(f"/api/v1/workspaces/{workspace.id}/ai/providers")
        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "openai",
                "displayName": "OpenAI",
                "capabilities": ["chat", "models"],
                "configured": True,
                "authMode": "apiKey",
                "models": ["gpt-live"],
                "defaultModels": {"answer": "gpt-live"},
            }
        ]
    finally:
        app.dependency_overrides.clear()

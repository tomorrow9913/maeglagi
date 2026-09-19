from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.main import app
from app.modules.context_engine.infrastructure.provider_registry import provider_registry


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

    assert set(item) == {"id", "displayName", "capabilities", "configured", "models"}
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

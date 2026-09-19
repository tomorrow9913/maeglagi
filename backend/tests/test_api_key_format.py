from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.api_key_format import api_key_format_error
from app.core.config import Settings
from app.core.database import get_session
from app.main import create_app
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.context_engine.infrastructure.provider_adapters import (
    AnthropicAdapter,
    OpenAICompatibleAdapter,
    ProviderError,
)

INVALID_KEYS = (
    "√private-test",
    "한글-private",
    "key\nprivate",
    "key\rprivate",
    "key\tprivate",
    "key\x00private",
    "key\x7fprivate",
    "key private",
)


@pytest.mark.parametrize("key", INVALID_KEYS)
@pytest.mark.parametrize("provider", ["openai", "anthropic", "nvidia", "ollama"])
async def test_invalid_key_never_reaches_provider(monkeypatch, key, provider):
    async def unexpected_request(*args, **kwargs):
        pytest.fail("Malformed key must be rejected before a provider request")

    monkeypatch.setattr(httpx.AsyncClient, "request", unexpected_request)
    valid, message = await validate_provider_credential(provider, key, "https://ollama.example")
    assert not valid
    assert key not in message


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_validation_and_model_preview_return_client_errors_without_secret(key):
    app = create_app(Settings(_env_file=None, rate_limit="1000/minute"))
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(uuid4()), metadata={})

    async def fake_session():
        yield SimpleNamespace(get=AsyncMock())

    app.dependency_overrides[get_session] = fake_session
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/llm-keys/validate", json={"provider": "openai", "apiKey": key}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert key not in response.text
        preview = client.post("/api/v1/llm-keys/models", json={"provider": "openai", "apiKey": key})
        assert preview.status_code == 422
        assert key not in preview.text


@pytest.mark.parametrize(
    "adapter",
    [
        OpenAICompatibleAdapter("nvidia", "NIM", "https://provider.example"),
        AnthropicAdapter(),
    ],
)
async def test_legacy_bad_key_raises_safe_provider_error(adapter):
    with pytest.raises(ProviderError, match="API 키") as error:
        adapter._headers("√private-legacy")
    assert "private-legacy" not in str(error.value)
    assert (await adapter.validate_credential("√private-legacy"))[0] is False


def test_ascii_keys_are_not_restricted_to_a_vendor_prefix_or_length():
    assert api_key_format_error("a") is None
    assert api_key_format_error("custom_key-123./+=") is None
    assert api_key_format_error("", allow_empty=True) is None
    assert api_key_format_error("") is not None

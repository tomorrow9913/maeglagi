import httpx
import pytest

from app.modules.context_engine.application.provider import (
    ChatMessage,
    EmbeddingRequest,
    StructuredOutputRequest,
)
from app.modules.context_engine.infrastructure.provider_adapters import ProviderCapabilityError
from app.modules.context_engine.infrastructure.provider_registry import provider_registry


def test_registry_exposes_only_registered_providers() -> None:
    assert [adapter.id for adapter in provider_registry.all()] == ["openai", "anthropic", "nvidia"]


def test_nvidia_uses_openai_compatible_capabilities() -> None:
    adapter = provider_registry.get("nvidia")

    assert adapter is not None
    assert adapter.display_name == "NVIDIA NIM"
    assert set(adapter.capabilities) == {"chat", "models"}


def test_unknown_provider_is_not_available() -> None:
    assert provider_registry.get("unknown") is None


def test_openai_exposes_completed_adapter_contract() -> None:
    adapter = provider_registry.get("openai")

    assert adapter is not None
    assert set(adapter.capabilities) == {
        "chat",
        "embedding",
        "structuredOutput",
        "models",
    }


@pytest.mark.asyncio
async def test_openai_embedding_normalizes_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
            headers={"x-request-id": "emb-123"},
        )

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=transport, **kwargs),
    )
    adapter = provider_registry.get("openai")
    assert adapter is not None

    response = await adapter.embedding(
        EmbeddingRequest(input=["first", "second"], model="text-embedding-3-small", dimensions=2),
        "secret",
    )

    assert response.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert response.provider == "openai"
    assert response.provider_metadata == {"request_id": "emb-123"}
    assert requests[0].url.path == "/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_openai_structured_output_sends_json_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"yes"}'}}],
                "model": "gpt-4.1-mini",
                "usage": {"total_tokens": 12},
            },
        )

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=transport, **kwargs),
    )
    adapter = provider_registry.get("openai")
    assert adapter is not None
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }

    response = await adapter.structured_output(
        StructuredOutputRequest(
            messages=[ChatMessage(role="user", content="Answer")],
            model="gpt-4.1-mini",
            schema_name="answer",
            json_schema=schema,
        ),
        "secret",
    )

    assert response.data == {"answer": "yes"}
    response_format = payloads[0]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["json_schema"] == {
        "name": "answer",
        "strict": True,
        "schema": schema,
    }


@pytest.mark.asyncio
async def test_unsupported_provider_keeps_contract_with_clear_error() -> None:
    adapter = provider_registry.get("anthropic")
    assert adapter is not None

    with pytest.raises(ProviderCapabilityError, match="embedding"):
        await adapter.embedding(EmbeddingRequest(input="text", model="unused"), "secret")

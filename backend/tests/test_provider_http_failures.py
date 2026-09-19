from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from app.modules.context_engine.application.provider import ChatMessage, ChatRequest
from app.modules.context_engine.infrastructure.provider_adapters import (
    OpenAICompatibleAdapter,
    ProviderError,
)
from app.modules.ingestion.infrastructure import source_processor


@pytest.mark.parametrize(
    "status,terminal", [(401, True), (403, True), (404, True), (429, False), (503, False)]
)
async def test_provider_status_is_preserved_without_response_secrets(monkeypatch, status, terminal):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text="private-response-secret")
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    adapter = OpenAICompatibleAdapter("nvidia", "NVIDIA NIM", "https://provider.example/v1")
    with pytest.raises(ProviderError) as caught:
        await adapter.chat(
            ChatRequest(model="retired-model", messages=[ChatMessage(role="user", content="test")]),
            "private-key",
        )
    safe = source_processor._safe_attempt_error(caught.value, "analyzing")
    assert safe.http_status == status
    assert safe.terminal is terminal
    assert "private" not in str(safe)
    assert "private" not in str(caught.value)


async def test_missing_model_fails_once_with_actionable_message(monkeypatch):
    updates = []

    @asynccontextmanager
    async def held_lock(_identifier):
        yield

    async def fail(_identifier):
        raise ProviderError("model unavailable", http_status=404)

    async def update(_identifier, **kwargs):
        updates.append(kwargs)
        return "analyzing"

    monkeypatch.setattr(source_processor, "_source_execution_lock", held_lock)
    monkeypatch.setattr(source_processor, "_process_source", fail)
    monkeypatch.setattr(source_processor, "_update_source", update)
    result = await source_processor.process_source_attempt(uuid4(), final_attempt=False)
    assert result.terminal and result.http_status == 404
    assert updates[0]["status"] == "failed"
    assert "추출 모델" in updates[0]["error_message"]

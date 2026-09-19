from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.context_engine.application.extraction import ExtractionError, ExtractionPipeline
from app.modules.context_engine.application.provider import ChatMessage, ChatRequest, ChatResponse
from app.modules.context_engine.domain.extraction import ClassificationOutput
from app.modules.context_engine.infrastructure.provider_adapters import (
    OpenAICompatibleAdapter,
    ProviderError,
)
from app.modules.ingestion.infrastructure import source_processor


async def test_nvidia_nonstream_chat_uses_bounded_read_timeout_only(monkeypatch):
    original = httpx.AsyncClient
    seen_timeouts = []
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "model": "test"},
        )

    def client(**kwargs):
        seen_timeouts.append(kwargs["timeout"])
        return original(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(
        "app.modules.context_engine.infrastructure.provider_adapters.get_settings",
        lambda: Settings(_env_file=None, nvidia_chat_read_timeout_seconds=240),
    )
    request = ChatRequest(model="test", messages=[ChatMessage(role="user", content="test")])
    await OpenAICompatibleAdapter("nvidia", "NIM", "https://example.test/v1").chat(request, "key")
    await OpenAICompatibleAdapter("openai", "OpenAI", "https://example.test/v1").chat(
        request, "key"
    )
    assert len(requests) == 2
    assert isinstance(seen_timeouts[0], httpx.Timeout)
    assert seen_timeouts[0].read == 240
    assert seen_timeouts[0].connect == 10
    assert seen_timeouts[1] == 60


@pytest.mark.parametrize("value", [59, 601])
def test_nvidia_read_timeout_rejects_out_of_range_values(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, nvidia_chat_read_timeout_seconds=value)


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("nvidia", "z-ai/glm-5.3-flash", {"reasoning_effort": "low"}),
        ("nvidia", "another-model", {}),
        ("openai", "z-ai/glm-5.3-flash", {}),
    ],
)
async def test_glm_reasoning_effort_is_limited_to_nvidia_extraction(
    monkeypatch, provider, model, expected
):
    class Adapter:
        id = provider
        display_name = provider
        capabilities = ("chat",)

        def __init__(self):
            self.requests = []

        async def chat(self, request, _key):
            self.requests.append(request)
            return ChatResponse(
                text='{"source_type":"meeting","language":"ko","topics":[]}',
                model=request.model,
                provider=self.id,
            )

    monkeypatch.setattr(
        "app.modules.context_engine.application.extraction.get_settings",
        lambda: Settings(_env_file=None, nvidia_glm_extraction_reasoning_effort="low"),
    )
    adapter = Adapter()
    pipeline = ExtractionPipeline(adapter, "key", model=model)
    await pipeline.run_stage("classification", "system", {"text": "sample"}, ClassificationOutput)
    assert adapter.requests[0].provider_options == expected


def test_timeout_extraction_stage_is_allowlisted_and_redacted():
    try:
        try:
            raise httpx.ReadTimeout("private-key-and-source")
        except httpx.ReadTimeout as cause:
            raise ProviderError("private-provider-response") from cause
    except ProviderError as cause:
        error = ExtractionError("entity", "private-source-text")
        error.__cause__ = cause
    safe = source_processor._safe_attempt_error(error, "graphing")
    assert safe.code == "http_timeout"
    assert safe.stage == "graphing"
    assert safe.extraction_stage == "entity"
    assert not safe.terminal
    assert "private" not in str(safe)
    assert source_processor._safe_attempt_error(
        ExtractionError("private-source-text", "private-key"), "graphing"
    ).extraction_stage is None


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

import json

import httpx
import pytest

from app.modules.context_engine.application.provider import ChatMessage, ChatRequest
from app.modules.context_engine.infrastructure import provider_adapters
from app.modules.context_engine.infrastructure.provider_adapters import (
    AnthropicAdapter,
    ProviderError,
)


def frame(kind, **values):
    return ("data: " + json.dumps({"type": kind, **values}) + "\n\n").encode()


class Frames(httpx.AsyncByteStream):
    def __init__(self, frames):
        self.frames = frames
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for value in self.frames:
            self.reads += 1
            if isinstance(value, Exception):
                raise value
            yield value

    async def aclose(self):
        self.closed = True


def connect(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        provider_adapters.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )


def request():
    return ChatRequest(
        model="claude-test",
        messages=[
            ChatMessage(role="system", content="근거를 인용하세요"),
            ChatMessage(role="user", content="질문"),
        ],
    )


async def test_incremental_delivery_system_mapping_and_cancellation(monkeypatch):
    body = Frames(
        [
            frame("content_block_delta", delta={"type": "text_delta", "text": "첫"}),
            frame("content_block_delta", delta={"type": "text_delta", "text": "끝"}),
            frame("message_stop"),
        ]
    )

    def handler(req):
        payload = json.loads(req.content)
        assert payload["system"] == "근거를 인용하세요"
        assert payload["messages"] == [{"role": "user", "content": "질문"}]
        assert payload["stream"] is True
        return httpx.Response(200, stream=body)

    connect(monkeypatch, handler)
    stream = AnthropicAdapter().stream(request(), "test-key")
    assert await anext(stream) == "첫"
    assert body.reads == 1
    await stream.aclose()
    assert body.closed


async def test_text_only_events_and_completion(monkeypatch):
    body = Frames(
        [
            b": keepalive\n\n",
            frame("ping"),
            frame("content_block_start", content_block={"type": "text", "text": ""}),
            frame("content_block_delta", delta={"type": "thinking_delta", "thinking": "private"}),
            frame("future_event"),
            frame("content_block_delta", delta={"type": "text_delta", "text": "답변[1]"}),
            frame("message_stop"),
        ]
    )
    connect(monkeypatch, lambda req: httpx.Response(200, stream=body))
    assert [text async for text in AnthropicAdapter().stream(request(), "key")] == ["답변[1]"]
    assert body.closed


@pytest.mark.parametrize(
    "tail",
    [
        [],
        [frame("error", error={"message": "secret-key"})],
        [b"data: invalid-json\n\n"],
        [httpx.ReadError("secret-key")],
    ],
)
async def test_partial_response_failure_is_sanitized(monkeypatch, tail):
    body = Frames([frame("content_block_delta", delta={"type": "text_delta", "text": "첫"}), *tail])
    connect(monkeypatch, lambda req: httpx.Response(200, stream=body))
    stream = AnthropicAdapter().stream(request(), "key")
    assert await anext(stream) == "첫"
    with pytest.raises(ProviderError) as error:
        await anext(stream)
    assert "secret-key" not in str(error.value)
    assert body.closed


async def test_http_failure_is_sanitized(monkeypatch):
    connect(monkeypatch, lambda req: httpx.Response(401, text="secret-key"))
    with pytest.raises(ProviderError, match="401") as error:
        await anext(AnthropicAdapter().stream(request(), "key"))
    assert "secret-key" not in str(error.value)


async def test_chat_system_mapping_and_text_extraction(monkeypatch):
    def handler(req):
        payload = json.loads(req.content)
        assert payload["stream"] is False
        assert payload["system"] == "근거를 인용하세요"
        assert all(m["role"] != "system" for m in payload["messages"])
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "thinking", "thinking": "private"},
                    {"type": "text", "text": "답변"},
                ],
                "usage": {"input_tokens": 3, "cache": None},
            },
        )

    connect(monkeypatch, handler)
    response = await AnthropicAdapter().chat(request(), "key")
    assert response.text == "답변"
    assert response.usage == {"input_tokens": 3}


@pytest.mark.parametrize("complete", [True, False])
async def test_ask_preserves_evidence_and_does_not_finish_a_failed_stream(monkeypatch, complete):
    from uuid import uuid4

    from app.modules.retrieval.application.answer import answer_events
    from app.modules.retrieval.application.hybrid import Evidence, RetrievalResult
    from app.modules.retrieval.domain.answer import AnswerSource

    source = AnswerSource(
        index=1,
        source_id=uuid4(),
        chunk_id=uuid4(),
        kind="meeting",
        title="회의",
        excerpt="결정",
        timestamp=12,
    )
    frames = [
        frame("content_block_delta", delta={"type": "text_delta", "text": part})
        for part in ["결정[", "1", "]"]
    ]
    frames.append(
        frame("message_stop") if complete else frame("error", error={"message": "secret"})
    )
    connect(monkeypatch, lambda req: httpx.Response(200, stream=Frames(frames)))
    events = [
        event
        async for event in answer_events(
            adapter=AnthropicAdapter(),
            api_key="key",
            model="claude-test",
            question="결정은?",
            retrieval=RetrievalResult(
                evidence=[Evidence(source=source, text="결정")], facts=[], entities=[]
            ),
            store=None,
        )
    ]
    assert events[0]["type"] == "sources"
    assert events[0]["sources"][0]["sourceId"] == str(source.source_id)
    assert events[0]["sources"][0]["timestamp"] == 12
    assert "".join(e["text"] for e in events if e["type"] == "token") == "결정[1]"
    assert events[-1]["type"] == ("done" if complete else "error")
    if not complete:
        assert not any(e["type"] == "done" for e in events)
        assert "secret" not in events[-1]["message"]

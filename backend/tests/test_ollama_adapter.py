import json

import httpx
import pytest

from app.core import credentials as credentials_module
from app.core.config import Settings
from app.modules.context_engine.application.model_roles import ModelRole, options_by_role
from app.modules.context_engine.application.provider import (
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    StructuredOutputRequest,
)
from app.modules.context_engine.infrastructure import provider_registry as registry_module
from app.modules.context_engine.infrastructure.ollama_adapter import OllamaAdapter
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError


@pytest.fixture
def local_server(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "local-chat:latest"},
                        {"name": "local-embed:latest"},
                        {"name": "wrong-embed:latest"},
                        {"name": "remote:cloud"},
                        {"name": "alias-chat:latest"},
                        {"name": "alias-embed:latest"},
                        {"name": "alias-model:latest"},
                        {"name": "alias-cap:latest"},
                    ]
                },
            )
        if path == "/api/show":
            name = json.loads(request.content)["model"]
            if name.startswith("alias-"):
                details = {"capabilities": ["completion", "embedding"]}
                if name in {"alias-chat:latest", "alias-embed:latest"}:
                    details["remote_host"] = "https://ollama.com"
                elif name == "alias-model:latest":
                    details["remote_model"] = "remote:cloud"
                else:
                    details["capabilities"].append("cloud")
                return httpx.Response(200, json=details)
            return httpx.Response(
                200,
                json={
                    "capabilities": ["completion"] if name == "local-chat:latest" else ["embedding"]
                },
            )
        if path == "/api/embed":
            payload = json.loads(request.content)
            width = 768 if payload["model"] == "wrong-embed:latest" else 1536
            amount = len(payload["input"]) if isinstance(payload["input"], list) else 1
            return httpx.Response(200, json={"embeddings": [[0.1] * width for _ in range(amount)]})
        if path == "/api/chat":
            payload = json.loads(request.content)
            if payload["stream"]:
                return httpx.Response(
                    200,
                    text=(
                        '{"message":{"content":"hello "},"done":false}\n'
                        '{"message":{"content":"world"},"done":false}\n'
                        '{"message":{"content":""},"done":true}\n'
                    ),
                )
            content = '{"ok":true}' if "format" in payload else "hello"
            return httpx.Response(
                200, json={"model": payload["model"], "message": {"content": content}, "done": True}
            )
        raise AssertionError(path)

    transport = httpx.MockTransport(handler)
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: actual_client(transport=transport, **kwargs)
    )
    return requests


@pytest.mark.asyncio
async def test_local_model_capabilities_and_1536_probe(local_server: list[httpx.Request]) -> None:
    adapter = OllamaAdapter("http://ollama:11434")
    assert await adapter.validate_credential("") == (True, "Ollama 로컬 서버에 연결되었습니다.")
    infos = await adapter.list_model_infos("")
    options = options_by_role([(adapter, infos)])

    assert [item.model for item in options[ModelRole.ANSWER]] == ["local-chat:latest"]
    assert [item.model for item in options[ModelRole.EMBEDDING]] == ["local-embed:latest"]
    assert not any(item.id.startswith("alias-") for item in infos)
    assert options[ModelRole.TRANSCRIPTION] == []
    assert all(b"remote:cloud" not in request.content for request in local_server)
    probes = [json.loads(r.content) for r in local_server if r.url.path == "/api/embed"]
    assert all(p["dimensions"] == 1536 and p["truncate"] is False for p in probes)


@pytest.mark.asyncio
async def test_native_chat_schema_stream_and_embedding(local_server: list[httpx.Request]) -> None:
    adapter = OllamaAdapter("http://ollama:11434")
    chat_request = ChatRequest(
        model="local-chat:latest", messages=[ChatMessage(role="user", content="hi")]
    )
    assert (await adapter.chat(chat_request, "")).text == "hello"
    assert [part async for part in adapter.stream(chat_request, "")] == ["hello ", "world"]
    structured = StructuredOutputRequest(
        model="local-chat:latest",
        messages=chat_request.messages,
        schema_name="answer",
        json_schema={"type": "object"},
    )
    assert (await adapter.structured_output(structured, "")).data == {"ok": True}
    embedded = await adapter.embedding(
        EmbeddingRequest(model="local-embed:latest", input=["a", "b"]), ""
    )
    assert len(embedded.embeddings) == 2 and len(embedded.embeddings[0]) == 1536
    chat_payloads = [json.loads(r.content) for r in local_server if r.url.path == "/api/chat"]
    assert chat_payloads[2]["format"] == {"type": "object"}
    assert all("authorization" not in r.headers for r in local_server)


@pytest.mark.asyncio
async def test_cloud_and_wrong_dimension_are_rejected(local_server: list[httpx.Request]) -> None:
    adapter = OllamaAdapter("http://ollama:11434")
    with pytest.raises(ProviderError, match="로컬"):
        await adapter.chat(ChatRequest(model="remote:cloud", messages=[]), "")
    with pytest.raises(ProviderError, match="차원"):
        await adapter.embedding(EmbeddingRequest(model="wrong-embed:latest", input="a"), "")
    assert not [r for r in local_server if r.url.path == "/api/chat"]


@pytest.mark.asyncio
async def test_remote_alias_is_rejected_before_user_content_is_sent(
    local_server: list[httpx.Request],
) -> None:
    adapter = OllamaAdapter("http://ollama:11434")
    chat = ChatRequest(
        model="alias-chat:latest", messages=[ChatMessage(role="user", content="PRIVATE PROMPT")]
    )
    for operation in (
        adapter.chat(chat, ""),
        adapter.structured_output(
            StructuredOutputRequest(
                model="alias-chat:latest",
                messages=chat.messages,
                schema_name="x",
                json_schema={"type": "object"},
            ),
            "",
        ),
        adapter.embedding(EmbeddingRequest(model="alias-embed:latest", input="PRIVATE PROMPT"), ""),
    ):
        with pytest.raises(ProviderError, match="원격"):
            await operation
    for alias in ("alias-model:latest", "alias-cap:latest"):
        with pytest.raises(ProviderError, match="원격"):
            await adapter.chat(chat.model_copy(update={"model": alias}), "")
    with pytest.raises(ProviderError, match="원격"):
        await anext(adapter.stream(chat, ""))
    assert not [r for r in local_server if r.url.path in {"/api/chat", "/api/embed"}]
    assert all(b"PRIVATE PROMPT" not in r.content for r in local_server)


@pytest.mark.asyncio
async def test_malformed_show_and_chat_json_become_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local:latest"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, text="invalid JSON")
        raise AssertionError("User payload must not be sent after malformed model metadata")

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    adapter = OllamaAdapter("http://ollama:11434")
    assert await adapter.list_model_infos("") == []
    with pytest.raises(ProviderError, match="정보"):
        await adapter.chat(ChatRequest(model="local:latest", messages=[]), "")

    def malformed_chat(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local:latest"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        if request.url.path == "/api/chat":
            return httpx.Response(200, text="invalid JSON")
        raise AssertionError(request.url.path)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(malformed_chat), **kwargs),
    )
    with pytest.raises(ProviderError):
        await adapter.chat(ChatRequest(model="local:latest", messages=[]), "")


def test_registry_requires_admin_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "get_settings", lambda: Settings(_env_file=None))
    assert registry_module.provider_registry.get("ollama") is None
    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: Settings(_env_file=None, ollama_base_url="http://ollama:11434"),
    )
    assert registry_module.provider_registry.get("ollama") is not None


@pytest.mark.asyncio
async def test_keyless_connection_never_reads_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        credentials_module,
        "get_settings",
        lambda: Settings(_env_file=None, ollama_base_url="http://ollama:11434"),
    )
    assert (
        await credentials_module.resolve_credential_secret(
            None, SimpleNamespace(provider="ollama", vault_secret_id=None)
        )
        == ""
    )

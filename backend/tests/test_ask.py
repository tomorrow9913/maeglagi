import importlib
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.application.provider import ChatMessage, ChatRequest
from app.modules.context_engine.infrastructure import provider_adapters
from app.modules.context_engine.infrastructure.models import Chunk, ContextStoreRecord
from app.modules.context_engine.infrastructure.provider_adapters import (
    OpenAICompatibleAdapter,
    ProviderError,
)
from app.modules.ingestion.application.pipeline import IngestionError, ResolvedProvider
from app.modules.retrieval.application.answer import (
    EMPTY_ANSWER,
    NO_EVIDENCE,
    CitationFilter,
    answer_events,
    build_messages,
)
from app.modules.retrieval.application.hybrid import (
    Evidence,
    GraphFact,
    HybridRetriever,
    RetrievalResult,
    understand_query,
)
from app.modules.retrieval.application.lexical import LexicalMatch
from app.modules.retrieval.domain.answer import AnswerSource
from app.modules.workspaces.domain.source_state import SourceStatus
from app.modules.workspaces.infrastructure.models import Source, Workspace

# The package re-exports the APIRouter as `router`, which shadows the submodule attribute.
ask_module = importlib.import_module("app.api.ask.router")

USER = uuid4()
WORKSPACE = uuid4()


# --- OpenAI-compatible streaming ----------------------------------------------------------------


def sse(*frames: str) -> str:
    return "".join(f"{frame}\n\n" for frame in frames)


def delta(text: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})


async def stream_text(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[str]:
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        provider_adapters.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=transport, **kwargs),
    )
    adapter = OpenAICompatibleAdapter("openai", "OpenAI", "https://api.example/v1")
    request = ChatRequest(messages=[ChatMessage(role="user", content="q")], model="m")
    return [piece async for piece in adapter.stream(request, "sk-test")]


async def test_the_openai_adapter_yields_tokens_as_they_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        body = sse(delta("안녕"), delta("하세요"), "data: [DONE]")
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    assert await stream_text(monkeypatch, handler) == ["안녕", "하세요"]
    assert seen["payload"]["stream"] is True
    assert seen["auth"] == "Bearer sk-test"


async def test_keepalives_empty_deltas_and_garbage_frames_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = ": keep-alive\n\n" + sse(
            "data: " + json.dumps({"choices": [{"delta": {"role": "assistant"}}]}),
            "data: {not json",
            delta("끝"),
            "data: [DONE]",
        )
        return httpx.Response(200, content=body)

    assert await stream_text(monkeypatch, handler) == ["끝"]


async def test_a_failing_provider_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderError, match="401"):
        await stream_text(monkeypatch, lambda request: httpx.Response(401, json={"error": "bad"}))


async def test_a_connection_failure_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProviderError, match="연결하지 못했습니다"):
        await stream_text(monkeypatch, handler)


# --- citation filter ----------------------------------------------------------------------------


def filtered(pieces: list[str], valid: set[int]) -> str:
    citations = CitationFilter(valid)
    text = "".join(citations.feed(piece) for piece in pieces)
    citations.flush()
    return text


def test_a_citation_split_across_tokens_is_kept_when_it_exists() -> None:
    assert filtered(["p95가 1.8초입니다", "[", "1", "]", "."], {1, 2}) == "p95가 1.8초입니다[1]."


def test_a_citation_to_missing_evidence_is_removed() -> None:
    assert filtered(["결정됐습니다[", "7", "]. 이유는 성능입니다[1]."], {1}) == (
        "결정됐습니다. 이유는 성능입니다[1]."
    )


def test_a_list_keeps_only_the_numbers_that_exist() -> None:
    assert filtered(["도입했습니다[1, 9]"], {1, 2}) == "도입했습니다[1]"
    assert filtered(["도입했습니다[8, 9]"], {1, 2}) == "도입했습니다"


def test_brackets_that_are_not_citations_pass_through() -> None:
    assert filtered(["[참고] 2026-09-12 [메모] 값[a]"], {1}) == "[참고] 2026-09-12 [메모] 값[a]"


def test_a_stray_bracket_before_a_citation_does_not_swallow_it() -> None:
    assert filtered(["[[1]"], {1}) == "[[1]"
    assert filtered(["[[9]"], {1}) == "["


def test_a_half_written_citation_at_the_end_is_dropped() -> None:
    assert filtered(["끝났습니다[", "1"], {1}) == "끝났습니다"


# --- query understanding ------------------------------------------------------------------------


ENTITIES = [
    {"name": "박지훈", "keys": ["박지훈"], "source_ids": [], "superseded": False},
    {"name": "Redis", "keys": ["redis"], "source_ids": [], "superseded": False},
    {"name": "가", "keys": ["가"], "source_ids": [], "superseded": False},
]


def test_the_entities_a_question_names_become_the_graph_starting_points() -> None:
    plan = understand_query("박지훈님이 Redis를 왜 도입했나요?", ENTITIES)

    assert [e["name"] for e in plan.entities] == ["박지훈", "Redis"]
    assert plan.semantic_query == "박지훈님이 Redis를 왜 도입했나요?"


def test_one_character_keys_and_unmentioned_entities_are_ignored() -> None:
    assert understand_query("가장 최근 결정은?", ENTITIES).entities == []


# --- hybrid retrieval ---------------------------------------------------------------------------


SOURCE_A = Source(
    id=uuid4(),
    workspace_id=WORKSPACE,
    owner_id=USER,
    kind="meeting",
    title="아키텍처 회의",
    object_path="a",
    content_type="text/plain",
    size_bytes=1,
    status=SourceStatus.SUCCEEDED,
)
SOURCE_B = Source(
    id=uuid4(),
    workspace_id=WORKSPACE,
    owner_id=USER,
    kind="document",
    title="기획서",
    object_path="b",
    content_type="text/plain",
    size_bytes=1,
    status=SourceStatus.SUCCEEDED,
)


def chunk(source: Source, text: str, start: float | None = None) -> Chunk:
    return Chunk(
        id=uuid4(), workspace_id=WORKSPACE, source_id=source.id, owner_id=USER,
        position=0, content=text, start_seconds=start,
    )  # fmt: skip


VECTOR = [0.25, 0.5]


class Embedder:
    """An `embed` that returns a fixed vector and counts how often it was asked."""

    def __init__(self) -> None:
        self.questions: list[str] = []

    async def __call__(self, question: str) -> list[float]:
        self.questions.append(question)
        return VECTOR


class Recorder:
    """A `search` that answers from a table and remembers how it was called."""

    def __init__(self, unscoped: list[Chunk], scoped: list[Chunk] | None = None) -> None:
        self.unscoped, self.scoped = unscoped, scoped or []
        self.calls: list[tuple[list[float], list[UUID] | None, int]] = []

    async def __call__(
        self, embedding: list[float], source_ids: list[UUID] | None, limit: int
    ) -> list[tuple[Chunk, float]]:
        self.calls.append((embedding, source_ids, limit))
        return [(c, 0.1) for c in (self.unscoped if source_ids is None else self.scoped)]


async def load_sources(ids: list[UUID]) -> dict[UUID, Source]:
    return {s.id: s for s in (SOURCE_A, SOURCE_B) if s.id in ids}


class FakeGraph:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def entities(self, workspace_id: UUID) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("neo4j down")
        return [
            {
                "name": "박지훈",
                "keys": ["박지훈"],
                "source_ids": [str(SOURCE_B.id)],
                "superseded": False,
            }
        ]

    async def facts(self, workspace_id: UUID, keys: list[str], at: Any) -> list[dict[str, Any]]:
        return [
            {
                "source": "캐시를 두지 않는다",
                "kind": "DECIDED_IN",
                "target": "기획 회의",
                "source_ids": [str(SOURCE_A.id), "not-a-uuid"],
                "superseded": ["캐시를 두지 않는다"],
            }
        ]


async def test_vector_hits_become_numbered_evidence_with_their_origin() -> None:
    first, second = chunk(SOURCE_A, "p95가 1.8초입니다.", 754.0), chunk(SOURCE_B, "목표는 500ms")
    retriever = HybridRetriever(
        embed=Embedder(), search=Recorder([first, second]), load_sources=load_sources
    )

    result = await retriever.retrieve(WORKSPACE, "지연은?")

    assert [e.source.index for e in result.evidence] == [1, 2]
    top = result.evidence[0].source
    assert (top.source_id, top.chunk_id, top.kind, top.timestamp) == (
        SOURCE_A.id, first.id, "meeting", 754.0
    )  # fmt: skip
    assert result.evidence[1].source.timestamp is None  # documents have no time to jump to


async def test_the_graph_widens_the_search_to_the_sources_it_points_at() -> None:
    from_vector, from_graph = chunk(SOURCE_A, "벡터"), chunk(SOURCE_B, "그래프")
    search = Recorder([from_vector], scoped=[from_graph, from_vector])
    retriever = HybridRetriever(
        embed=Embedder(), search=search, load_sources=load_sources, graph=FakeGraph()
    )  # type: ignore[arg-type]

    result = await retriever.retrieve(WORKSPACE, "박지훈은 무엇을 결정했나요?")

    assert [e.text for e in result.evidence] == ["벡터", "그래프"]  # deduplicated, vector first
    assert search.calls[0][1] is None
    assert set(search.calls[1][1] or []) == {SOURCE_A.id, SOURCE_B.id}  # bad ids are ignored
    assert result.entities == ["박지훈"]
    assert result.facts == [
        GraphFact("캐시를 두지 않는다", "DECIDED_IN", "기획 회의", ["캐시를 두지 않는다"])
    ]


async def test_a_graph_failure_falls_back_to_vector_search() -> None:
    search = Recorder([chunk(SOURCE_A, "벡터")])
    retriever = HybridRetriever(
        embed=Embedder(), search=search, load_sources=load_sources, graph=FakeGraph(fail=True)
    )  # type: ignore[arg-type]

    result = await retriever.retrieve(WORKSPACE, "박지훈은?")

    assert [e.text for e in result.evidence] == ["벡터"]
    assert result.facts == [] and len(search.calls) == 1


async def test_a_chunk_whose_source_is_gone_is_dropped_and_numbering_stays_contiguous() -> None:
    orphan = Chunk(
        id=uuid4(), workspace_id=WORKSPACE, source_id=uuid4(), owner_id=USER,
        position=0, content="고아", start_seconds=None,
    )  # fmt: skip
    retriever = HybridRetriever(
        embed=Embedder(),
        search=Recorder([orphan, chunk(SOURCE_A, "살아 있음")]),
        load_sources=load_sources,
    )

    result = await retriever.retrieve(WORKSPACE, "q")

    assert [(e.source.index, e.text) for e in result.evidence] == [(1, "살아 있음")]


async def test_the_number_of_evidence_items_is_capped() -> None:
    many = [chunk(SOURCE_A, f"t{i}") for i in range(20)]
    retriever = HybridRetriever(
        embed=Embedder(), search=Recorder(many), load_sources=load_sources, max_evidence=5
    )

    assert len((await retriever.retrieve(WORKSPACE, "q")).evidence) == 5


# --- answer events ------------------------------------------------------------------------------


def evidence(index: int, text: str, timestamp: float | None = None) -> Evidence:
    return Evidence(
        source=AnswerSource(
            index=index, source_id=uuid4(), chunk_id=uuid4(), kind="meeting",
            title="회의", excerpt=text, timestamp=timestamp,
        ),
        text=text,
    )  # fmt: skip


class ScriptedAdapter:
    id, display_name, capabilities = "fake", "Fake", ("chat", "embedding")

    def __init__(
        self,
        pieces: list[str] | None = None,
        fail_after: int | None = None,
        streaming: bool = True,
        chat_text: str = "한 번에 온 답",
    ) -> None:
        self.pieces = pieces or []
        self.fail_after = fail_after
        self.streaming = streaming
        self.chat_text = chat_text
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        self.requests.append(request)
        if not self.streaming:
            raise NotImplementedError
        for index, piece in enumerate(self.pieces):
            if self.fail_after is not None and index >= self.fail_after:
                raise ProviderError("모델 요청에 실패했습니다 (500).")
            yield piece

    async def chat(self, request: ChatRequest, api_key: str) -> Any:
        self.requests.append(request)
        return type("Chat", (), {"text": self.chat_text})()


async def collect(
    adapter: ScriptedAdapter, result: RetrievalResult, store: Any = None
) -> list[dict]:
    return [
        event
        async for event in answer_events(
            adapter=adapter,  # type: ignore[arg-type]
            api_key="k",
            model="m",
            question="Redis를 왜 도입했나요?",
            retrieval=result,
            store=store,
        )
    ]


def found(*items: Evidence) -> RetrievalResult:
    return RetrievalResult(evidence=list(items), facts=[], entities=[])


async def test_sources_come_first_then_tokens_then_done() -> None:
    adapter = ScriptedAdapter(["p95가 320ms로 ", "내려갔습니다[1]."])

    events = await collect(adapter, found(evidence(1, "320ms", 754.0)))

    assert [e["type"] for e in events] == ["sources", "token", "token", "done"]
    (source,) = events[0]["sources"]
    assert set(source) == {"index", "sourceId", "chunkId", "kind", "title", "excerpt", "timestamp"}
    assert source["timestamp"] == 754.0
    assert (
        "".join(e["text"] for e in events if e["type"] == "token")
        == "p95가 320ms로 내려갔습니다[1]."
    )


async def test_no_evidence_ends_in_an_error_without_calling_the_model() -> None:
    adapter = ScriptedAdapter(["절대 안 나옴"])

    events = await collect(adapter, found())

    assert events == [{"type": "error", "message": NO_EVIDENCE}]
    assert adapter.requests == []


async def test_citations_to_evidence_that_does_not_exist_never_reach_the_client() -> None:
    adapter = ScriptedAdapter(["근거는 이렇습니다[1] 그리고 [", "5", "]저것."])

    events = await collect(adapter, found(evidence(1, "근거")))

    assert (
        "".join(e["text"] for e in events if e["type"] == "token")
        == "근거는 이렇습니다[1] 그리고 저것."
    )


async def test_a_provider_failure_mid_stream_ends_in_an_error_not_done() -> None:
    adapter = ScriptedAdapter(["일부", "잘림"], fail_after=1)

    events = await collect(adapter, found(evidence(1, "근거")))

    assert [e["type"] for e in events] == ["sources", "token", "error"]
    assert "500" in events[-1]["message"]


async def test_an_empty_model_answer_is_reported_instead_of_a_bare_done() -> None:
    events = await collect(ScriptedAdapter([]), found(evidence(1, "근거")))

    assert events[-1] == {"type": "error", "message": EMPTY_ANSWER}


async def test_a_provider_without_streaming_answers_in_one_piece() -> None:
    adapter = ScriptedAdapter(streaming=False, chat_text="통째로 답합니다[1].")

    events = await collect(adapter, found(evidence(1, "근거")))

    assert [e["type"] for e in events] == ["sources", "token", "done"]
    assert events[1]["text"] == "통째로 답합니다[1]."


async def test_the_model_is_told_to_cite_and_to_distrust_replaced_decisions() -> None:
    from app.modules.context_engine.domain.context_store import ContextStoreState, StoreDecision

    store = ContextStoreState(
        subject="맥락이 PoC",
        current_state="Redis 도입이 결정됐다.",
        decisions=[StoreDecision(title="Redis 도입", description="", source_refs=["x"])],
    )
    result = RetrievalResult(
        evidence=[evidence(1, "320ms 달성", 65.0), evidence(2, "1.8초 확인")],
        facts=[GraphFact("캐시를 두지 않는다", "DECIDED_IN", "기획 회의", ["캐시를 두지 않는다"])],
        entities=[],
    )

    system, user = build_messages("왜 Redis?", result, store)

    assert system.role == "system" and "[1]" in system.content and "대체" in system.content
    assert "[1] (회의: 회의, 01:05)\n320ms 달성" in user.content
    assert "[2] (회의: 회의)\n1.8초 확인" in user.content
    assert "유효한 결정: Redis 도입" in user.content
    assert "캐시를 두지 않는다 -DECIDED_IN-> 기획 회의 (대체됨: 캐시를 두지 않는다)" in user.content
    assert user.content.endswith("질문: 왜 Redis?")


async def test_a_workspace_without_a_context_store_still_gets_a_prompt() -> None:
    _, user = build_messages("q", found(evidence(1, "근거")), None)

    assert "아직 정리된 현재 상황이 없습니다" in user.content


# --- the endpoint -------------------------------------------------------------------------------


class FakeSession:
    def __init__(self, owner: UUID) -> None:
        self.owner = owner

    async def get(self, model: Any, identifier: Any) -> Workspace | None:
        if identifier != WORKSPACE:
            return None
        return Workspace(id=WORKSPACE, owner_id=self.owner, name="맥락이 PoC")

    async def exec(self, statement: Any) -> Any:
        text = str(statement)
        rows: list[Any] = []
        if "context_stores" in text:
            rows = [
                ContextStoreRecord(
                    workspace_id=WORKSPACE,
                    owner_id=USER,
                    subject="맥락이 PoC",
                    current_state="Redis 도입이 결정됐다.",
                )  # fmt: skip
            ]
        elif "FROM sources" in text:
            rows = [SOURCE_A]
        return type(
            "R", (), {"all": lambda self: rows, "first": lambda self: rows[0] if rows else None}
        )()


class FakeIngestion:
    """Stands in for IngestionPipeline: hands out a scripted chat adapter and canned chunks."""

    adapter = ScriptedAdapter(["Redis를 도입해 p95가 ", "320ms로 내려갔습니다[1][4]."])
    chunks: list[Chunk] = []
    no_chat_key = False
    no_embedding_key = False

    def __init__(self, settings: Any = None) -> None:
        pass

    embed_calls: list[str] = []
    searches: list[dict[str, Any]] = []
    answer_model = "chosen-answer-model"

    async def provider_with_model(self, session: Any, **kwargs: Any) -> Any:
        if self.no_chat_key:
            raise IngestionError("chat을 지원하는 API key가 없습니다.")
        return ResolvedProvider(self.adapter, "sk-test", self.answer_model)

    async def embed_query(self, session: Any, **kwargs: Any) -> list[float]:
        if self.no_embedding_key:
            raise IngestionError("embedding을 지원하는 API key가 없습니다.")
        self.embed_calls.append(kwargs["query"])
        return VECTOR

    async def search_by_embedding(self, session: Any, **kwargs: Any) -> list[tuple[Chunk, float]]:
        self.searches.append(kwargs)
        return [(c, 0.1) for c in self.chunks]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    FakeIngestion.chunks = [chunk(SOURCE_A, "Redis 캐시 적용 후 p95가 320ms", 754.0)]
    FakeIngestion.no_chat_key = FakeIngestion.no_embedding_key = False
    FakeIngestion.embed_calls, FakeIngestion.searches = [], []
    FakeIngestion.adapter = ScriptedAdapter(
        ["Redis를 도입해 p95가 ", "320ms로 내려갔습니다[1][4]."]
    )
    monkeypatch.setattr(ask_module, "IngestionPipeline", FakeIngestion)

    async def lexical(session: Any, **kwargs: Any) -> list[LexicalMatch]:
        return [
            LexicalMatch(
                c.source_id, c.id, SOURCE_A.kind, SOURCE_A.title, c.content, c.start_seconds
            )
            for c in FakeIngestion.chunks
            if "redis" in c.content.lower()
        ]

    monkeypatch.setattr(ask_module, "search_lexically", lexical)

    async def session() -> Any:
        yield FakeSession(USER)

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def read_events(response: Any) -> list[Any]:
    """Parse the body exactly as the frontend's `apiStream` does."""
    events: list[Any] = []
    for line in response.text.split("\n"):
        trimmed = line.strip()
        if not trimmed.startswith("data:"):
            continue
        payload = trimmed[5:].strip()
        if payload == "[DONE]":
            return events
        events.append(json.loads(payload))
    raise AssertionError("stream did not end with [DONE]")


def ask(
    client: TestClient, question: str = "Redis를 왜 도입했나요?", workspace: UUID = WORKSPACE
) -> Any:
    return client.post(f"/api/v1/workspaces/{workspace}/ask", json={"question": question})


def test_the_endpoint_streams_sources_tokens_and_done_as_server_sent_events(
    client: TestClient,
) -> None:
    response = ask(client)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = read_events(response)
    assert [e["type"] for e in events] == ["sources", "token", "token", "done"]
    (source,) = events[0]["sources"]
    assert source["sourceId"] == str(SOURCE_A.id) and source["title"] == "아키텍처 회의"
    assert source["timestamp"] == 754.0
    # [4] cites evidence that does not exist, so it never reaches the client.
    assert "".join(e["text"] for e in events if e["type"] == "token") == (
        "Redis를 도입해 p95가 320ms로 내려갔습니다[1]."
    )


def test_the_model_sees_the_workspaces_current_situation(client: TestClient) -> None:
    ask(client)

    user_message = FakeIngestion.adapter.requests[0].messages[1].content
    assert "Redis 도입이 결정됐다." in user_message
    assert "Redis 캐시 적용 후 p95가 320ms" in user_message


def test_no_matching_chunks_is_an_error_event_and_the_model_is_not_called(
    client: TestClient,
) -> None:
    FakeIngestion.chunks = []

    events = read_events(ask(client))

    assert events == [{"type": "error", "message": NO_EVIDENCE}]
    assert FakeIngestion.adapter.requests == []


def test_a_mid_stream_crash_is_reported_without_leaking_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "sources", "sources": []}
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(ask_module, "answer_events", boom)

    events = read_events(ask(client))

    assert [e["type"] for e in events] == ["sources", "error"]
    assert "secret" not in json.dumps(events)


def test_someone_elses_or_an_unknown_workspace_is_a_404(client: TestClient) -> None:
    assert ask(client, workspace=uuid4()).status_code == 404

    async def foreign() -> Any:
        yield FakeSession(uuid4())

    app.dependency_overrides[get_session] = foreign
    assert ask(client).status_code == 404


def test_a_workspace_without_an_answer_key_is_a_422_before_any_streaming(
    client: TestClient,
) -> None:
    FakeIngestion.no_chat_key = True
    chat = ask(client)
    assert chat.status_code == 422 and "chat" in chat.json()["detail"]


def test_answer_only_key_uses_keyword_evidence(client: TestClient) -> None:
    FakeIngestion.no_embedding_key = True

    events = read_events(ask(client))

    assert [event["type"] for event in events] == ["sources", "token", "token", "done"]
    assert events[0]["sources"][0]["sourceId"] == str(SOURCE_A.id)
    assert len(FakeIngestion.adapter.requests) == 1


def test_processed_source_text_has_a_valid_source_only_citation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeIngestion.chunks = []

    async def source_text(session: Any, **kwargs: Any) -> list[LexicalMatch]:
        return [LexicalMatch(SOURCE_A.id, None, SOURCE_A.kind, SOURCE_A.title, "Redis 도입 결정")]

    monkeypatch.setattr(ask_module, "search_lexically", source_text)
    events = read_events(ask(client))

    assert [event["type"] for event in events] == ["sources", "token", "token", "done"]
    assert events[0]["sources"][0]["sourceId"] == str(SOURCE_A.id)
    assert "chunkId" not in events[0]["sources"][0]
    assert "Redis 도입 결정" in FakeIngestion.adapter.requests[0].messages[1].content


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_a_blank_or_oversized_question_is_rejected(client: TestClient, question: str) -> None:
    assert ask(client, question).status_code == 422


def test_the_route_is_registered() -> None:
    assert "/api/v1/workspaces/{workspace_id}/ask" in app.openapi()["paths"]
    assert ask_module.router.prefix == "/workspaces"


async def test_the_question_is_embedded_once_and_both_searches_reuse_it() -> None:
    embed = Embedder()
    search = Recorder([chunk(SOURCE_A, "벡터")], scoped=[chunk(SOURCE_B, "그래프")])
    retriever = HybridRetriever(
        embed=embed,
        search=search,
        load_sources=load_sources,
        graph=FakeGraph(),  # type: ignore[arg-type]
    )

    await retriever.retrieve(WORKSPACE, "박지훈은 무엇을 했나요?")

    assert embed.questions == ["박지훈은 무엇을 했나요?"]  # embedded once, not once per search
    assert len(search.calls) == 2  # the plain search and the graph-scoped one
    assert [call[0] for call in search.calls] == [VECTOR, VECTOR]


async def test_keyword_fallback_deduplicates_and_bounds_citations() -> None:
    item = LexicalMatch(SOURCE_A.id, uuid4(), SOURCE_A.kind, SOURCE_A.title, "결정 내용")

    async def unavailable(question: str) -> list[float]:
        raise IngestionError("embedding unavailable")

    async def lexical(
        question: str, source_ids: list[UUID] | None, limit: int
    ) -> list[LexicalMatch]:
        return [
            item,
            item,
            *[
                LexicalMatch(SOURCE_A.id, uuid4(), SOURCE_A.kind, SOURCE_A.title, "결정 내용")
                for _ in range(20)
            ],
        ]

    retriever = HybridRetriever(
        embed=unavailable,
        search=Recorder([]),
        load_sources=load_sources,
        lexical_search=lexical,
        max_evidence=4,
    )
    result = await retriever.retrieve(WORKSPACE, "결정은?")

    assert len(result.evidence) == 4
    assert [e.source.index for e in result.evidence] == [1, 2, 3, 4]
    assert len({e.source.chunk_id for e in result.evidence}) == 4


async def test_vector_evidence_from_unreviewed_source_is_excluded() -> None:
    draft = SOURCE_A.model_copy(update={"status": SourceStatus.AWAITING_REVIEW})

    async def draft_sources(ids: list[UUID]) -> dict[UUID, Source]:
        return {draft.id: draft}

    retriever = HybridRetriever(
        embed=Embedder(),
        search=Recorder([chunk(SOURCE_A, "비공개 초안")]),
        load_sources=draft_sources,
    )
    assert (await retriever.retrieve(WORKSPACE, "초안")).evidence == []


def test_the_endpoint_embeds_once_and_answers_with_the_model_the_workspace_chose(
    client: TestClient,
) -> None:
    FakeIngestion.answer_model = "the-model-the-user-picked"
    ask(client)

    assert FakeIngestion.embed_calls == ["Redis를 왜 도입했나요?"]
    assert FakeIngestion.adapter.requests[0].model == "the-model-the-user-picked"

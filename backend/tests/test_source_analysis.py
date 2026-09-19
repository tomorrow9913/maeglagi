import asyncio
import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.modules.context_engine.application.context_store import (
    ContextStoreService,
    ContextStoreUpdater,
)
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.application.provider import ChatRequest, ChatResponse
from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord
from app.modules.ingestion.application.pipeline import IngestionError, ResolvedProvider
from app.modules.ingestion.application.source_analysis import (
    SourceAnalysisService,
    analyze_source,
)
from app.modules.ingestion.infrastructure import tasks
from app.modules.workspaces.infrastructure.models import Source, Workspace
from tests.seeds import SEEDS
from tests.test_entity_resolution import FakeStore
from tests.test_extraction_pipeline import ChatAdapter, FakeAdapter

WORKSPACE = uuid4()
OWNER = uuid4()
SOURCE = uuid4()


class FakeRepository:
    def __init__(self, record: ContextStoreRecord | None = None) -> None:
        self.record = record
        self.timeline: dict[UUID, list[ContextRecord]] = {}

    async def load(self, workspace_id: UUID) -> ContextStoreRecord | None:
        return self.record

    async def save(self, record: ContextStoreRecord) -> None:
        self.record = record

    async def replace_timeline(self, source_id: UUID, rows: list[ContextRecord]) -> None:
        self.timeline[source_id] = rows


def stored_record(*decision_titles: str) -> ContextStoreRecord:
    return ContextStoreRecord(
        workspace_id=WORKSPACE,
        owner_id=OWNER,
        subject="맥락이 PoC",
        summary="이전 요약",
        current_state="이전 상황",
        decisions=[
            {"title": t, "description": "", "source_refs": ["근거"], "decided_at": None}
            for t in decision_titles
        ],
    )


def architecture_meeting() -> Any:
    return next(seed for seed in SEEDS if seed.name == "meeting-0912")


def responses_replacing_the_no_cache_decision() -> dict[str, Any]:
    responses = copy.deepcopy(architecture_meeting().responses)
    for event in responses["event"]["events"]:
        if event["kind"] == "Decision":
            event["supersedes"] = "캐시를 두지 않는다"
    return responses


def context_store(adapter: FakeAdapter, repository: FakeRepository) -> ContextStoreService:
    pipeline = ExtractionPipeline(adapter, "key", model="test-model")  # type: ignore[arg-type]
    return ContextStoreService(repository, ContextStoreUpdater(pipeline))


async def analyze(
    adapter: FakeAdapter,
    repository: FakeRepository,
    graph_store: FakeStore | None = None,
) -> list[str]:
    return await analyze_source(
        adapter=adapter,  # type: ignore[arg-type]
        api_key="key",
        model="test-model",
        context_store=context_store(adapter, repository),
        graph_store=graph_store,  # type: ignore[arg-type]
        workspace_id=WORKSPACE,
        owner_id=OWNER,
        source_id=SOURCE,
        title="아키텍처 회의",
        subject="맥락이 PoC",
        text=architecture_meeting().text,
    )


async def test_one_extraction_feeds_the_timeline_the_store_and_the_graph() -> None:
    adapter = FakeAdapter(architecture_meeting().responses)
    repository, graph = FakeRepository(), FakeStore()

    warnings = await analyze(adapter, repository, graph)

    stages = [r.schema_name for r in adapter.requests]
    assert stages == [
        f"extraction_{s}" for s in ("classification", "entity", "event", "relation", "context")
    ] + ["extraction_context_update"]
    assert {r.kind for r in repository.timeline[SOURCE]} == {"event", "decision", "task"}
    assert repository.record is not None
    assert [d["title"] for d in repository.record.decisions] == ["Redis 도입 결정"]
    assert {row["name"] for row in graph.rows("MERGE (e:Entity {id: row.id})")} >= {
        "Redis 도입 결정"
    }
    assert warnings == []


async def test_invalid_chat_extraction_never_writes_store_or_graph() -> None:
    repository, graph = FakeRepository(), FakeStore()
    adapter = ChatAdapter(overrides={"classification": ["{}", "{}"]})

    with pytest.raises(Exception, match="classification"):
        await analyze(adapter, repository, graph)  # type: ignore[arg-type]

    assert repository.record is None
    assert repository.timeline == {}
    assert graph.calls == []


async def test_chat_extraction_also_validates_context_store_update() -> None:
    seed = architecture_meeting()

    class SourceChatAdapter(ChatAdapter):
        async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
            if "ContextUpdateOutput" in request.messages[0].content:
                return ChatResponse(
                    text=json.dumps(seed.responses["context_update"]),
                    model=request.model,
                    provider=self.id,
                )
            return await super().chat(request, api_key)

    adapter = SourceChatAdapter()
    repository, graph = FakeRepository(), FakeStore()

    await analyze(adapter, repository, graph)  # type: ignore[arg-type]

    assert repository.record is not None
    assert repository.record.current_state == "현재 상황"
    assert repository.timeline[SOURCE]
    assert graph.calls


async def test_invalid_chat_context_update_never_writes_store_or_graph() -> None:
    class InvalidUpdateAdapter(ChatAdapter):
        async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
            if "ContextUpdateOutput" in request.messages[0].content:
                return ChatResponse(text="{}", model=request.model, provider=self.id)
            return await super().chat(request, api_key)

    adapter = InvalidUpdateAdapter()
    repository, graph = FakeRepository(), FakeStore()

    with pytest.raises(Exception, match="context_update"):
        await analyze(adapter, repository, graph)  # type: ignore[arg-type]

    assert repository.record is None
    assert repository.timeline == {}
    assert graph.calls == []


async def test_decisions_offered_for_replacement_come_from_the_context_store() -> None:
    adapter = FakeAdapter(architecture_meeting().responses)

    await analyze(adapter, FakeRepository(stored_record("캐시를 두지 않는다")))

    event_request = next(r for r in adapter.requests if r.schema_name == "extraction_event")
    assert json.loads(event_request.messages[1].content)["known_decisions"] == [
        "캐시를 두지 않는다"
    ]


async def test_a_replacing_decision_removes_the_old_one_from_the_store_and_links_the_graph() -> (
    None
):
    repository = FakeRepository(stored_record("캐시를 두지 않는다"))
    graph = FakeStore(superseded=[{"new_id": "x", "id": str(uuid4())}])

    await analyze(FakeAdapter(responses_replacing_the_no_cache_decision()), repository, graph)

    assert repository.record is not None
    assert [d["title"] for d in repository.record.decisions] == ["Redis 도입 결정"]
    (row,) = graph.rows("SET old.superseded_by")
    assert row["keys"] == ["캐시를두지않는다"]


async def test_the_store_is_still_updated_without_neo4j() -> None:
    repository = FakeRepository()

    warnings = await analyze(FakeAdapter(architecture_meeting().responses), repository, None)

    assert repository.record is not None
    assert repository.record.current_state == "현재 상황"
    assert any("Neo4j가 설정되지 않아" in warning for warning in warnings)


async def test_the_upload_date_is_not_invented_as_a_relation_start() -> None:
    graph = FakeStore()

    await analyze(FakeAdapter(architecture_meeting().responses), FakeRepository(), graph)

    assert all(r["valid_from"] is None for r in graph.rows("MERGE (a)-[r:PARTICIPATED_IN"))


# --- service: skipping where the workspace cannot support analysis -----------------------------


def source() -> Source:
    return Source(
        id=SOURCE,
        workspace_id=WORKSPACE,
        owner_id=OWNER,
        kind="meeting",
        title="회의",
        object_path="p",
        content_type="text/plain",
        size_bytes=1,
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def get(self, model: Any, identifier: Any) -> Any:
        return Workspace(id=WORKSPACE, owner_id=OWNER, name="맥락이 PoC")

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


class NoChatKey:
    async def provider_with_model(self, session: Any, **kwargs: Any) -> Any:
        raise IngestionError("chat을 지원하는 API key가 없습니다.")


class WithKey:
    """A workspace whose owner chose `chosen-extraction-model` for analysis."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter
        self.roles: list[Any] = []

    async def provider_with_model(self, session: Any, **kwargs: Any) -> Any:
        self.roles.append(kwargs["role"])
        return ResolvedProvider(self.adapter, "key", "chosen-extraction-model")


async def test_analysis_is_skipped_without_a_chat_key() -> None:
    service = SourceAnalysisService(NoChatKey(), Settings(_env_file=None))  # type: ignore[arg-type]

    warnings = await service.run(FakeSession(), source=source(), text="본문")  # type: ignore[arg-type]

    assert len(warnings) == 1
    assert "chat" in warnings[0]


async def test_analysis_service_skips_unconfirmed_meeting_before_provider_lookup() -> None:
    meeting = source()
    meeting.review_state = "awaiting_review"
    service = SourceAnalysisService(NoChatKey(), Settings(_env_file=None))  # type: ignore[arg-type]

    warnings = await service.run(FakeSession(), source=meeting, text="본문")  # type: ignore[arg-type]

    assert "대본 확인" in warnings[0]


async def test_the_service_names_the_store_after_the_workspace_and_releases_its_lock() -> None:
    repository, session = FakeRepository(), FakeSession()
    service = SourceAnalysisService(
        WithKey(FakeAdapter(architecture_meeting().responses)),  # type: ignore[arg-type]
        Settings(_env_file=None),
        repository_factory=lambda _: repository,
    )

    await service.run(session, source=source(), text=architecture_meeting().text)  # type: ignore[arg-type]

    assert repository.record is not None
    assert repository.record.subject == "맥락이 PoC"
    assert session.commits == 3  # extraction, context/phase, and completed checkpoint


# --- the Celery task calls it ---------------------------------------------------------------


class FakeTaskSession:
    def __init__(self, record: Source) -> None:
        self.record = record

    async def __aenter__(self) -> "FakeTaskSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, model: Any, identifier: Any) -> Source:
        return self.record

    async def exec(self, statement: Any) -> Any:
        class Result:
            def first(self) -> Source:
                return self_record

        self_record = self.record
        return Result()

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass


class StubIngestion:
    index_calls = 0

    async def index_source(self, session: Any, **kwargs: Any) -> int:
        type(self).index_calls += 1
        return 1

    async def transcribe(self, session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(text="서버 원문", duration_seconds=5, segments=[])


class RecordingAnalysis:
    calls: list[dict[str, Any]] = []
    error: Exception | None = None

    async def run(self, session: Any, *, source: Source, text: str) -> list[str]:
        self.calls.append(
            {"text": text, "stage": source.processing_stage, "progress": source.progress}
        )
        if self.error:
            raise self.error
        return []


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Any:
    RecordingAnalysis.calls = []
    RecordingAnalysis.error = None
    StubIngestion.index_calls = 0

    def install(record: Source, download: bytes = b"") -> None:
        async def fake_download(_: Source) -> bytes:
            return download

        monkeypatch.setattr(tasks, "session_factory", lambda: FakeTaskSession(record))
        monkeypatch.setattr(tasks, "_download_source", fake_download)
        monkeypatch.setattr(tasks, "IngestionPipeline", StubIngestion)
        monkeypatch.setattr(tasks, "SourceAnalysisService", RecordingAnalysis)

    return install


async def test_a_document_is_analyzed_from_its_parsed_text(wired: Any) -> None:
    record = source()
    record.kind, record.title = "document", "plan.md"
    wired(record, "# 기획서\n담당: 박지훈".encode())

    await tasks._process_source(record.id)

    (call,) = RecordingAnalysis.calls
    assert call["text"] == "# 기획서\n담당: 박지훈"
    assert (call["stage"], call["progress"]) == ("graphing", 0.7)
    assert (record.status, record.processing_stage) == ("succeeded", "completed")


async def test_a_browser_transcript_meeting_is_analyzed_from_its_transcript(wired: Any) -> None:
    record = source()
    record.transcript_source, record.transcript_text = "browser", "지훈: Redis를 도입합시다."
    record.review_state = "confirmed"
    record.review_utterances = [{"id": "1", "speakerName": "지훈", "text": "Redis를 도입합시다."}]
    wired(record)

    await tasks._process_source(record.id)

    assert [c["text"] for c in RecordingAnalysis.calls] == ["지훈: Redis를 도입합시다."]
    assert record.status == "succeeded"


async def test_an_analysis_failure_fails_the_job_instead_of_reporting_success(wired: Any) -> None:
    record = source()
    record.transcript_source, record.transcript_text = "browser", "본문"
    record.review_state = "confirmed"
    record.review_utterances = [{"id": "1", "speakerName": "화자 1", "text": "본문"}]
    wired(record)
    RecordingAnalysis.error = RuntimeError("Neo4j down")

    with pytest.raises(RuntimeError, match="Neo4j down"):
        await tasks._process_source(record.id)

    assert record.status != "succeeded"


async def test_unconfirmed_meeting_never_indexes_or_analyzes(wired: Any) -> None:
    record = source()
    record.transcript_source = "browser"
    record.review_state = "awaiting_review"
    record.status = "awaiting_review"
    wired(record)

    await tasks._process_source(record.id)

    assert RecordingAnalysis.calls == []
    assert record.status == "awaiting_review"


async def test_server_stt_stops_at_review_and_keeps_live_edits(wired: Any) -> None:
    record = source()
    record.transcript_source = "server"
    record.review_state = "transcribing"
    record.review_utterances = [
        {"id": "live-1", "speakerName": "지훈", "text": "사람이 수정한 문장"}
    ]
    wired(record, b"audio")

    await tasks._process_source(record.id)

    assert record.status == record.processing_stage == "awaiting_review"
    assert record.raw_transcript_text == "서버 원문"
    assert record.review_utterances[0]["text"] == "사람이 수정한 문장"
    assert StubIngestion.index_calls == 0
    assert RecordingAnalysis.calls == []


async def test_final_stt_failure_is_retryable_without_downstream_writes(
    wired: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = source()
    record.transcript_source = "server"
    record.review_state = "transcribing"
    record.review_utterances = [
        {"id": "live-1", "speakerName": "지훈", "text": "사람이 수정한 문장"}
    ]
    wired(record, b"audio")

    async def fail_transcription(self: Any, session: Any, **kwargs: Any) -> Any:
        raise RuntimeError("transcription provider unavailable")

    @asynccontextmanager
    async def held_lock(source_id: UUID) -> Any:
        yield

    monkeypatch.setattr(StubIngestion, "transcribe", fail_transcription)
    monkeypatch.setattr(tasks, "_source_execution_lock", held_lock)

    error = await tasks._run_source_attempt(record.id, final_attempt=True)

    assert isinstance(error, RuntimeError)
    assert (record.status, record.review_state, record.processing_stage) == (
        "failed",
        "transcribing",
        "transcribing",
    )
    assert record.review_utterances[0]["text"] == "사람이 수정한 문장"
    assert StubIngestion.index_calls == 0
    assert RecordingAnalysis.calls == []


async def test_duplicate_confirmed_job_does_not_index_twice(wired: Any) -> None:
    record = source()
    record.transcript_source = "browser"
    record.review_state = "confirmed"
    record.transcript_text = "민수: 수정본"
    record.review_utterances = [{"id": "1", "speakerName": "민수", "text": "수정본"}]
    wired(record)

    await tasks._process_source(record.id)
    await tasks._process_source(record.id)

    assert StubIngestion.index_calls == 1
    assert len(RecordingAnalysis.calls) == 1


async def test_redelivered_processing_job_resumes_after_worker_loss(wired: Any) -> None:
    record = source()
    record.transcript_source = "browser"
    record.review_state = "confirmed"
    record.status = "processing"  # The dead worker committed this before it died.
    record.transcript_text = "민수: 수정본"
    record.review_utterances = [{"id": "1", "speakerName": "민수", "text": "수정본"}]
    wired(record)

    await tasks._process_source(record.id)

    assert record.status == "succeeded"
    assert StubIngestion.index_calls == 1
    assert len(RecordingAnalysis.calls) == 1


async def test_concurrent_attempts_wait_then_recheck_succeeded_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = asyncio.Lock()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    status = "processing"

    @asynccontextmanager
    async def held_lock(source_id: UUID) -> Any:
        async with lock:
            yield

    async def process(source_id: UUID) -> None:
        nonlocal calls, status
        if status == "succeeded":
            return
        calls += 1
        entered.set()
        await release.wait()
        status = "succeeded"

    monkeypatch.setattr(tasks, "_source_execution_lock", held_lock)
    monkeypatch.setattr(tasks, "_process_source", process)
    identifier = uuid4()
    first = asyncio.create_task(tasks._run_source_attempt(identifier, final_attempt=False))
    await entered.wait()
    second = asyncio.create_task(tasks._run_source_attempt(identifier, final_attempt=False))
    await asyncio.sleep(0)
    assert calls == 1
    release.set()
    assert await asyncio.gather(first, second) == [None, None]
    assert calls == 1


async def test_advisory_lock_keeps_a_dedicated_transaction_until_attempt_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class Connection:
        async def __aenter__(self) -> "Connection":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

        async def execute(self, statement: Any, parameters: Any = None) -> None:
            statements.append(str(statement))

        async def rollback(self) -> None:
            statements.append("ROLLBACK")

    class Engine:
        def connect(self) -> Connection:
            return Connection()

    monkeypatch.setattr(tasks, "engine", Engine())
    async with tasks._source_execution_lock(uuid4()):
        assert any("pg_advisory_xact_lock" in statement for statement in statements)
        assert "ROLLBACK" not in statements
    assert statements[-1] == "ROLLBACK"
    assert not any("pg_try_advisory_lock" in statement for statement in statements)


async def test_analysis_uses_the_extraction_model_the_workspace_chose() -> None:
    adapter = FakeAdapter(architecture_meeting().responses)
    ingestion = WithKey(adapter)
    service = SourceAnalysisService(
        ingestion,  # type: ignore[arg-type]
        Settings(_env_file=None),
        repository_factory=lambda _: FakeRepository(),
    )

    await service.run(FakeSession(), source=source(), text=architecture_meeting().text)  # type: ignore[arg-type]

    assert [role.value for role in ingestion.roles] == ["extraction"]
    assert {r.model for r in adapter.requests} == {"chosen-extraction-model"}


async def test_partial_graph_write_replays_checkpoint_without_reextracting_or_reapplying_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartialGraph(FakeStore):
        failed = False

        async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
            if "MERGE (a)-[r:" in query and not self.failed:
                self.failed = True
                raise RuntimeError("Neo4j stopped after entity write")
            return await super().execute(query, parameters)

        async def close(self) -> None:
            pass

    graph = PartialGraph()
    monkeypatch.setattr(
        "app.modules.ingestion.application.source_analysis.Neo4jGraphStore.from_settings",
        lambda settings: graph,
    )
    settings = Settings(
        _env_file=None,
        neo4j_uri="bolt://localhost",
        neo4j_username="neo4j",
        neo4j_password="test",
    )
    record, repository, session = source(), FakeRepository(), FakeSession()
    record.review_state = "confirmed"
    adapter = FakeAdapter(architecture_meeting().responses)
    service = SourceAnalysisService(
        WithKey(adapter),
        settings,
        repository_factory=lambda _: repository,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="Neo4j stopped"):
        await service.run(session, source=record, text=architecture_meeting().text)  # type: ignore[arg-type]
    assert record.analysis_checkpoint["phase"] == "context_applied"
    assert session.commits == 2
    initial_requests = len(adapter.requests)
    timeline_ids = [row.id for row in repository.timeline[record.id]]
    initial_entities = graph.rows("MERGE (e:Entity {id: row.id})")

    await service.run(session, source=record, text=architecture_meeting().text)  # type: ignore[arg-type]

    assert len(adapter.requests) == initial_requests
    assert [row.id for row in repository.timeline[record.id]] == timeline_ids
    assert record.analysis_checkpoint["phase"] == "done"
    entity_writes = [
        params["rows"] for query, params in graph.calls if "MERGE (e:Entity {id: row.id})" in query
    ]
    assert entity_writes == [initial_entities, initial_entities]


async def test_committed_analysis_checkpoint_skips_provider_and_graph_on_redelivery() -> None:
    record, session = source(), FakeSession()
    record.review_state = "confirmed"
    first = SourceAnalysisService(
        WithKey(FakeAdapter(architecture_meeting().responses)),  # type: ignore[arg-type]
        Settings(_env_file=None),
        repository_factory=lambda _: FakeRepository(),
    )
    warnings = await first.run(session, source=record, text=architecture_meeting().text)  # type: ignore[arg-type]
    assert record.analysis_checkpoint["phase"] == "done"
    commits = session.commits

    resumed = SourceAnalysisService(NoChatKey(), Settings(_env_file=None))  # type: ignore[arg-type]
    assert await resumed.run(session, source=record, text=architecture_meeting().text) == warnings  # type: ignore[arg-type]
    assert session.commits == commits


async def test_task_resumes_committed_analysis_without_reindexing(wired: Any) -> None:
    record = source()
    record.kind = "document"
    record.content_text = "persisted document"
    record.analysis_checkpoint = {"phase": "done"}
    wired(record)

    await tasks._process_source(record.id)

    assert record.status == "succeeded"
    assert StubIngestion.index_calls == 0
    assert RecordingAnalysis.calls[0]["text"] == "persisted document"


async def test_worker_loss_after_analysis_commit_resumes_without_reindexing(
    wired: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = source()
    record.kind = "document"
    record.title = "plan.md"
    wired(record, b"persisted document")

    class CommitThenDie:
        calls = 0

        async def run(self, session: Any, *, source: Source, text: str) -> list[str]:
            type(self).calls += 1
            if type(self).calls == 1:
                source.analysis_checkpoint = {"phase": "done"}
                session.add(source)
                await session.commit()
                raise RuntimeError("worker lost after analysis commit")
            return []

    monkeypatch.setattr(tasks, "SourceAnalysisService", CommitThenDie)
    with pytest.raises(RuntimeError, match="worker lost"):
        await tasks._process_source(record.id)
    assert record.analysis_checkpoint["phase"] == "done"
    assert StubIngestion.index_calls == 1

    await tasks._process_source(record.id)
    assert record.status == "succeeded"
    assert StubIngestion.index_calls == 1
    assert CommitThenDie.calls == 2


def test_infrastructure_retries_do_not_consume_application_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bool, dict[str, Any]]] = []

    async def infrastructure_failure(source_id: UUID, *, final_attempt: bool) -> Any:
        calls.append((final_attempt, {}))
        raise ConnectionError("advisory lock unavailable")

    def retry(**kwargs: Any) -> Exception:
        calls[-1] = (calls[-1][0], kwargs)
        return RuntimeError("scheduled retry")

    monkeypatch.setattr(tasks, "_run_source_attempt", infrastructure_failure)
    monkeypatch.setattr(tasks.process_source, "retry", retry)
    tasks.process_source.push_request(retries=100)
    try:
        with pytest.raises(RuntimeError, match="scheduled retry"):
            tasks.process_source.run(str(SOURCE), app_attempt=1)
    finally:
        tasks.process_source.pop_request()

    assert calls[0][0] is False
    assert calls[0][1]["kwargs"] == {"app_attempt": 1}
    assert calls[0][1]["countdown"] == 30


def test_provider_failure_advances_only_application_attempt_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retries: list[dict[str, Any]] = []

    async def provider_failure(source_id: UUID, *, final_attempt: bool) -> Exception:
        assert final_attempt is False
        return RuntimeError("provider unavailable")

    def retry(**kwargs: Any) -> Exception:
        retries.append(kwargs)
        return RuntimeError("scheduled retry")

    monkeypatch.setattr(tasks, "_run_source_attempt", provider_failure)
    monkeypatch.setattr(tasks.process_source, "retry", retry)
    tasks.process_source.push_request(retries=100)
    try:
        with pytest.raises(RuntimeError, match="scheduled retry"):
            tasks.process_source.run(str(SOURCE), app_attempt=2)
    finally:
        tasks.process_source.pop_request()

    assert retries[0]["kwargs"] == {"app_attempt": 3}

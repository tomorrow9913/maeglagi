import copy
import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.modules.context_engine.application.context_store import (
    ContextStoreService,
    ContextStoreUpdater,
)
from app.modules.context_engine.application.extraction import ExtractionPipeline
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
from tests.test_extraction_pipeline import FakeAdapter

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

    async def commit(self) -> None:
        self.commits += 1


class NoStructuredOutputKey:
    async def provider_with_model(self, session: Any, **kwargs: Any) -> Any:
        raise IngestionError("structuredOutput을 지원하는 API key가 없습니다.")


class WithKey:
    """A workspace whose owner chose `chosen-extraction-model` for analysis."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter
        self.roles: list[Any] = []

    async def provider_with_model(self, session: Any, **kwargs: Any) -> Any:
        self.roles.append(kwargs["role"])
        return ResolvedProvider(self.adapter, "key", "chosen-extraction-model")


async def test_analysis_is_skipped_without_a_structured_output_key() -> None:
    service = SourceAnalysisService(NoStructuredOutputKey(), Settings(_env_file=None))  # type: ignore[arg-type]

    warnings = await service.run(FakeSession(), source=source(), text="본문")  # type: ignore[arg-type]

    assert len(warnings) == 1
    assert "structuredOutput" in warnings[0]


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
    assert session.commits == 1  # commits right after the store update so the row lock is freed


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

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass


class StubIngestion:
    async def index_source(self, session: Any, **kwargs: Any) -> int:
        return 1


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
    wired(record)

    await tasks._process_source(record.id)

    assert [c["text"] for c in RecordingAnalysis.calls] == ["지훈: Redis를 도입합시다."]
    assert record.status == "succeeded"


async def test_an_analysis_failure_fails_the_job_instead_of_reporting_success(wired: Any) -> None:
    record = source()
    record.transcript_source, record.transcript_text = "browser", "본문"
    wired(record)
    RecordingAnalysis.error = RuntimeError("Neo4j down")

    with pytest.raises(RuntimeError, match="Neo4j down"):
        await tasks._process_source(record.id)

    assert record.status != "succeeded"


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

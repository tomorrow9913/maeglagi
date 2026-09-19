import copy
import json
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.ingestion.application.graph_extraction import (
    GraphExtractionService,
    extract_into_graph,
)
from app.modules.ingestion.application.pipeline import IngestionError
from app.modules.ingestion.infrastructure import tasks
from app.modules.workspaces.infrastructure.models import Source
from tests.seeds import SEEDS
from tests.test_entity_resolution import FakeStore
from tests.test_extraction_pipeline import FakeAdapter

WORKSPACE = uuid4()
SOURCE = uuid4()
STORED_DECISIONS = [
    {
        "id": str(uuid4()),
        "name": "캐시를 두지 않는다",
        "decided_at": "2026-09-01T00:00:00Z",
        "superseded_by": None,
        "superseded_by_name": None,
    },
    {
        "id": str(uuid4()),
        "name": "예전에 이미 대체된 결정",
        "decided_at": "2026-08-01T00:00:00Z",
        "superseded_by": str(uuid4()),
        "superseded_by_name": "캐시를 두지 않는다",
    },
]


class DecisionStore(FakeStore):
    """FakeStore that also answers the stored-decisions query."""

    async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        if "OPTIONAL MATCH (n:Entity {id: d.superseded_by" in query:
            self.calls.append((query, parameters or {}))
            return STORED_DECISIONS
        return await super().execute(query, parameters)


def architecture_meeting() -> Any:
    return next(seed for seed in SEEDS if seed.name == "meeting-0912")


def responses_replacing_the_no_cache_decision() -> dict[str, Any]:
    responses = copy.deepcopy(architecture_meeting().responses)
    for event in responses["event"]["events"]:
        if event["kind"] == "Decision":
            event["supersedes"] = "캐시를 두지 않는다"
    return responses


async def run(adapter: FakeAdapter, store: FakeStore) -> list[str]:
    return await extract_into_graph(
        adapter=adapter,  # type: ignore[arg-type]
        api_key="key",
        store=store,  # type: ignore[arg-type]
        model="test-model",
        workspace_id=WORKSPACE,
        source_id=SOURCE,
        title="아키텍처 회의",
        text=architecture_meeting().text,
    )


async def test_extraction_runs_and_the_merged_graph_is_written() -> None:
    store = DecisionStore()

    warnings = await run(FakeAdapter(architecture_meeting().responses), store)

    names = {row["name"] for row in store.rows("MERGE (e:Entity {id: row.id})")}
    assert {"박지훈", "최서연", "이도윤", "Redis", "Redis 도입 결정"} <= names
    assert store.rows("MERGE (a)-[r:PARTICIPATED_IN")  # relations were written too
    assert warnings == []


async def test_only_unreplaced_stored_decisions_are_offered_to_the_event_stage() -> None:
    adapter = FakeAdapter(architecture_meeting().responses)

    await run(adapter, DecisionStore())

    event_request = next(r for r in adapter.requests if r.schema_name == "extraction_event")
    payload = json.loads(event_request.messages[1].content)
    assert payload["known_decisions"] == ["캐시를 두지 않는다"]


async def test_a_new_decision_replaces_the_stored_one_it_names() -> None:
    store = DecisionStore(superseded=[{"new_id": "x", "id": STORED_DECISIONS[0]["id"]}])

    await run(FakeAdapter(responses_replacing_the_no_cache_decision()), store)

    (row,) = store.rows("SET old.superseded_by")
    assert row["keys"] == ["캐시를두지않는다"]
    new_decision = next(
        r for r in store.rows("MERGE (e:Entity {id: row.id})") if r["name"] == "Redis 도입 결정"
    )
    assert row["new_id"] == new_decision["id"]


async def test_the_upload_date_is_not_invented_as_a_relation_start() -> None:
    store = DecisionStore()

    await run(FakeAdapter(architecture_meeting().responses), store)

    assert all(r["valid_from"] is None for r in store.rows("MERGE (a)-[r:PARTICIPATED_IN"))


# --- service: skipping where the workspace cannot support graph extraction -----------------


def source() -> Source:
    return Source(
        id=SOURCE,
        workspace_id=WORKSPACE,
        owner_id=uuid4(),
        kind="meeting",
        title="회의",
        object_path="p",
        content_type="text/plain",
        size_bytes=1,
    )


class NoStructuredOutputKey:
    async def provider_for(self, session: Any, **kwargs: Any) -> Any:
        raise IngestionError("structuredOutput을 지원하는 API key가 없습니다.")


class ExplodingIngestion:
    async def provider_for(self, session: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not look for a provider when Neo4j is off")


async def test_graph_extraction_is_skipped_without_neo4j() -> None:
    service = GraphExtractionService(ExplodingIngestion(), Settings(_env_file=None))  # type: ignore[arg-type]

    warnings = await service.run(None, source=source(), text="본문")  # type: ignore[arg-type]

    assert warnings == ["그래프 추출을 건너뛰었습니다: Neo4j가 설정되지 않았습니다."]


async def test_graph_extraction_is_skipped_without_a_structured_output_key() -> None:
    settings = Settings(
        _env_file=None,
        neo4j_uri="neo4j+s://example",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )
    service = GraphExtractionService(NoStructuredOutputKey(), settings)  # type: ignore[arg-type]

    warnings = await service.run(None, source=source(), text="본문")  # type: ignore[arg-type]

    assert len(warnings) == 1
    assert "structuredOutput" in warnings[0]


# --- the Celery task calls it ---------------------------------------------------------------


class FakeSession:
    def __init__(self, record: Source) -> None:
        self.record = record

    async def __aenter__(self) -> "FakeSession":
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


class RecordingGraph:
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
    RecordingGraph.calls = []
    RecordingGraph.error = None

    def install(record: Source, download: bytes = b"") -> None:
        async def fake_download(_: Source) -> bytes:
            return download

        monkeypatch.setattr(tasks, "session_factory", lambda: FakeSession(record))
        monkeypatch.setattr(tasks, "_download_source", fake_download)
        monkeypatch.setattr(tasks, "IngestionPipeline", StubIngestion)
        monkeypatch.setattr(tasks, "GraphExtractionService", RecordingGraph)

    return install


async def test_a_document_is_extracted_from_its_parsed_text(wired: Any) -> None:
    record = source()
    record.kind, record.title = "document", "plan.md"
    wired(record, "# 기획서\n담당: 박지훈".encode())

    await tasks._process_source(record.id)

    (call,) = RecordingGraph.calls
    assert call["text"] == "# 기획서\n담당: 박지훈"
    assert (call["stage"], call["progress"]) == ("graphing", 0.7)
    assert (record.status, record.processing_stage) == ("succeeded", "completed")


async def test_a_browser_transcript_meeting_is_extracted_from_its_transcript(wired: Any) -> None:
    record = source()
    record.transcript_source, record.transcript_text = "browser", "지훈: Redis를 도입합시다."
    wired(record)

    await tasks._process_source(record.id)

    assert [c["text"] for c in RecordingGraph.calls] == ["지훈: Redis를 도입합시다."]
    assert record.status == "succeeded"


async def test_a_graph_failure_fails_the_job_instead_of_reporting_success(wired: Any) -> None:
    record = source()
    record.transcript_source, record.transcript_text = "browser", "본문"
    wired(record)
    RecordingGraph.error = RuntimeError("Neo4j down")

    with pytest.raises(RuntimeError, match="Neo4j down"):
        await tasks._process_source(record.id)

    assert record.status != "succeeded"

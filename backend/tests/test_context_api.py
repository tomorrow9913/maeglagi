from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord
from app.modules.workspaces.infrastructure.models import Source, Workspace

USER = uuid4()
WORKSPACE = uuid4()
MEETING = Source(
    id=uuid4(),
    workspace_id=WORKSPACE,
    owner_id=USER,
    kind="meeting",
    title="아키텍처 회의",
    object_path="a",
    content_type="text/plain",
    size_bytes=1,
)
DOCUMENT = Source(
    id=uuid4(),
    workspace_id=WORKSPACE,
    owner_id=USER,
    kind="document",
    title="기획서",
    object_path="b",
    content_type="text/plain",
    size_bytes=1,
)


def record(
    kind: str,
    title: str,
    day: int | None,
    source: Source = MEETING,
    **metadata: Any,
) -> ContextRecord:
    return ContextRecord(
        id=uuid4(),
        workspace_id=WORKSPACE,
        source_id=source.id,
        owner_id=USER,
        kind=kind,
        title=title,
        body=f"{title} 설명",
        occurred_at=datetime(2026, 9, day, tzinfo=UTC) if day else None,
        metadata_={"key": title.replace(" ", ""), **metadata},
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


NO_CACHE = record("decision", "캐시를 두지 않는다", 1, DOCUMENT)
REDIS = record("decision", "Redis 도입", 12, supersedes="캐시를두지않는다")
LATENCY = record("issue", "응답 지연", 5)
TASK = record("task", "무효화 규칙", 13)
UNDATED = record("event", "날짜 없는 이벤트", None)


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, owner: UUID, store: ContextStoreRecord | None = None) -> None:
        self.owner = owner
        self.store = store

    async def get(self, model: Any, identifier: Any) -> Workspace | None:
        if identifier != WORKSPACE:
            return None
        return Workspace(id=WORKSPACE, owner_id=self.owner, name="맥락이 PoC")

    async def exec(self, statement: Any) -> FakeResult:
        if "context_stores" in str(statement):
            return FakeResult([self.store] if self.store else [])
        pairs = [
            (r, DOCUMENT if r is NO_CACHE else MEETING)
            for r in (NO_CACHE, REDIS, LATENCY, TASK, UNDATED)
        ]
        return FakeResult(pairs)


def as_owner(owner: UUID, store: ContextStoreRecord | None = None) -> None:
    async def session() -> Any:
        yield FakeSession(owner, store)

    app.dependency_overrides[get_session] = session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    as_owner(USER)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def timeline(client: TestClient, **params: Any) -> Any:
    return client.get(f"/api/v1/workspaces/{WORKSPACE}/context", params=params)


def test_the_timeline_has_the_shape_the_frontend_already_expects(client: TestClient) -> None:
    items = timeline(client).json()

    redis = next(i for i in items if i["title"] == "Redis 도입")
    assert set(redis) >= {"id", "kind", "title", "summary", "occurredAt", "sources"}
    assert redis["summary"] == "Redis 도입 설명"
    assert redis["sources"] == [
        {"id": str(MEETING.id), "kind": "meeting", "title": "아키텍처 회의", "chunkId": None}
    ]


def test_items_come_newest_first_and_undated_ones_fall_back_to_their_creation_time(
    client: TestClient,
) -> None:
    titles = [i["title"] for i in timeline(client).json()]

    assert titles == [
        "날짜 없는 이벤트",
        "무효화 규칙",
        "Redis 도입",
        "응답 지연",
        "캐시를 두지 않는다",
    ]


def test_a_replaced_decision_points_at_the_decision_that_replaced_it(client: TestClient) -> None:
    items = {i["title"]: i for i in timeline(client).json()}

    assert items["캐시를 두지 않는다"]["supersededBy"] == str(REDIS.id)
    assert items["Redis 도입"]["supersededBy"] is None
    assert items["응답 지연"]["supersededBy"] is None  # only explicit replacement counts


def test_filters_use_the_repeated_parameters_the_frontend_sends(client: TestClient) -> None:
    kinds = timeline(client, kind=["decision", "issue"]).json()
    assert {i["kind"] for i in kinds} == {"decision", "issue"}

    documents = timeline(client, source_kind="document").json()
    assert [i["title"] for i in documents] == ["캐시를 두지 않는다"]


def test_from_and_to_are_inclusive(client: TestClient) -> None:
    window = timeline(client, **{"from": "2026-09-05T00:00:00Z", "to": "2026-09-12T00:00:00Z"})

    assert [i["title"] for i in window.json()] == ["Redis 도입", "응답 지연"]


def test_someone_elses_workspace_is_a_404(client: TestClient) -> None:
    as_owner(uuid4())

    assert timeline(client).status_code == 404
    assert client.get(f"/api/v1/workspaces/{WORKSPACE}/context-store").status_code == 404


def test_an_unknown_workspace_is_a_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/workspaces/{uuid4()}/context").status_code == 404


def test_the_store_is_null_until_a_source_has_been_analyzed(client: TestClient) -> None:
    response = client.get(f"/api/v1/workspaces/{WORKSPACE}/context-store")

    assert response.status_code == 200
    assert response.json() is None


def test_the_store_reports_the_current_situation(client: TestClient) -> None:
    as_owner(
        USER,
        ContextStoreRecord(
            workspace_id=WORKSPACE,
            owner_id=USER,
            subject="맥락이 PoC",
            summary="요약",
            current_state="Redis 도입이 결정됐다.",
            open_issues=[{"title": "정합성", "description": "d", "source_refs": ["근거"]}],
            decisions=[
                {
                    "title": "Redis 도입",
                    "description": "",
                    "source_refs": ["근거"],
                    "decided_at": "2026-09-12",
                }
            ],
            next_actions=[
                {
                    "title": "무효화 규칙",
                    "description": "",
                    "source_refs": [],
                    "assignee": "최서연",
                    "due_at": "2026-09-19",
                }
            ],
            source_ids=["s1"],
            updated_at=datetime(2026, 9, 13, tzinfo=UTC),
        ),
    )

    body = client.get(f"/api/v1/workspaces/{WORKSPACE}/context-store").json()

    assert body["currentState"] == "Redis 도입이 결정됐다."
    assert [i["title"] for i in body["openIssues"]] == ["정합성"]
    assert body["decisions"][0]["decidedAt"] == "2026-09-12"
    assert (body["nextActions"][0]["assignee"], body["nextActions"][0]["dueAt"]) == (
        "최서연",
        "2026-09-19",
    )
    assert body["sourceIds"] == ["s1"]
    assert body["updatedAt"].startswith("2026-09-13")

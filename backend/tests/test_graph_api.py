from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.workspaces.graph import get_graph_store
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.workspaces.infrastructure.models import Source, Workspace

USER = uuid4()
WORKSPACE = uuid4()
OLD, NEW, PERSON, MEETING, TASK, BLOCKER = (str(uuid4()) for _ in range(6))
SOURCE = uuid4()

NODES = [
    {
        "id": PERSON,
        "kind": "Person",
        "name": "박지훈",
        "source_ids": [str(SOURCE)],
        "superseded_by": None,
    },
    {
        "id": OLD,
        "kind": "Decision",
        "name": "캐시를 두지 않는다",
        "source_ids": [],
        "superseded_by": NEW,
    },
    {
        "id": NEW,
        "kind": "Decision",
        "name": "Redis 도입",
        "source_ids": [str(SOURCE)],
        "superseded_by": None,
    },
    {
        "id": MEETING,
        "kind": "Meeting",
        "name": "아키텍처 회의",
        "source_ids": [],
        "superseded_by": None,
    },
    {"id": TASK, "kind": "Task", "name": "무효화 규칙", "source_ids": [], "superseded_by": None},
    {
        "id": BLOCKER,
        "kind": "Issue",
        "name": "정합성 문제",
        "source_ids": [],
        "superseded_by": None,
    },
]
EDGES = [
    {
        "id": "e1",
        "source": PERSON,
        "target": MEETING,
        "kind": "PARTICIPATED_IN",
        "valid_from": "2026-09-12T00:00:00Z",
        "valid_to": None,
    },
    {
        "id": None,
        "source": TASK,
        "target": BLOCKER,
        "kind": "BLOCKED_BY",
        "valid_from": None,
        "valid_to": None,
    },
    {
        "id": "e3",
        "source": PERSON,
        "target": NEW,
        "kind": "CREATED",
        "valid_from": None,
        "valid_to": "2026-12-31T00:00:00Z",
    },
    {
        "id": "e4",
        "source": PERSON,
        "target": str(uuid4()),
        "kind": "WORKS_ON",
        "valid_from": None,
        "valid_to": None,
    },  # points at a node that is not in the workspace
]


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        self.calls.append((query, parameters or {}))
        return NODES if "RETURN e.id AS id" in query else EDGES


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(self, owner: UUID) -> None:
        self.owner = owner

    async def get(self, model: Any, identifier: Any) -> Workspace | None:
        if identifier != WORKSPACE:
            return None
        return Workspace(id=WORKSPACE, owner_id=self.owner, name="ws")

    async def exec(self, statement: Any) -> FakeResult:
        entities = [item.get("entity") for item in getattr(statement, "column_descriptions", [])]
        if Source not in entities:
            return FakeResult([])
        return FakeResult(
            [
                Source(
                    id=SOURCE,
                    workspace_id=WORKSPACE,
                    owner_id=USER,
                    kind="meeting",
                    title="아키텍처 회의",
                    object_path="p",
                    content_type="text/plain",
                    size_bytes=1,
                )
            ]
        )


@pytest.fixture
def api() -> Iterator[tuple[TestClient, FakeStore]]:
    store = FakeStore()

    async def session() -> Any:
        yield FakeSession(USER)

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_graph_store] = lambda: store
    try:
        yield TestClient(app), store
    finally:
        app.dependency_overrides.clear()


def fetch(client: TestClient, workspace: UUID = WORKSPACE, **params: str) -> Any:
    return client.get(f"/api/v1/workspaces/{workspace}/graph", params=params)


def test_the_graph_matches_the_shape_the_frontend_already_expects(
    api: tuple[TestClient, FakeStore],
) -> None:
    body = fetch(api[0]).json()

    assert set(body) == {"nodes", "edges"}
    node = next(n for n in body["nodes"] if n["id"] == PERSON)
    assert node["label"] == "박지훈"
    assert node["type"] == "person"
    assert node["sources"] == [{"id": str(SOURCE), "kind": "meeting", "title": "아키텍처 회의"}]
    assert {"id", "source", "target", "type"} <= set(body["edges"][0])


def test_ontology_kinds_are_mapped_to_the_frontend_types_without_losing_the_kind(
    api: tuple[TestClient, FakeStore],
) -> None:
    nodes = {n["id"]: n for n in fetch(api[0]).json()["nodes"]}

    assert (nodes[MEETING]["type"], nodes[MEETING]["kind"]) == ("event", "Meeting")
    assert (nodes[BLOCKER]["type"], nodes[BLOCKER]["kind"]) == ("event", "Issue")
    assert nodes[NEW]["type"] == "decision"


def test_a_replaced_decision_gets_a_supersedes_edge_from_its_successor(
    api: tuple[TestClient, FakeStore],
) -> None:
    body = fetch(api[0]).json()

    supersedes = [e for e in body["edges"] if e["type"] == "supersedes"]
    assert [(e["source"], e["target"]) for e in supersedes] == [(NEW, OLD)]
    old = next(n for n in body["nodes"] if n["id"] == OLD)
    assert old["supersededBy"] == NEW


def test_relation_types_and_direction_follow_the_frontend_vocabulary(
    api: tuple[TestClient, FakeStore],
) -> None:
    edges = {e["kind"]: e for e in fetch(api[0]).json()["edges"] if e["kind"] != "SUPERSEDES"}

    assert edges["PARTICIPATED_IN"]["type"] == "participates_in"
    assert edges["CREATED"]["type"] == "relates_to"
    blocks = edges["BLOCKED_BY"]  # "task blocked by issue" is drawn as "issue blocks task"
    assert (blocks["type"], blocks["source"], blocks["target"]) == ("blocks", BLOCKER, TASK)
    assert blocks["id"] == f"{BLOCKER}-BLOCKED_BY-{TASK}"


def test_edges_expose_their_validity_and_dangling_edges_are_dropped(
    api: tuple[TestClient, FakeStore],
) -> None:
    edges = fetch(api[0]).json()["edges"]

    joined = next(e for e in edges if e["kind"] == "PARTICIPATED_IN")
    assert (joined["validFrom"], joined["validTo"]) == ("2026-09-12T00:00:00Z", None)
    assert all(e["kind"] != "WORKS_ON" for e in edges)


def test_degree_counts_the_drawn_edges(api: tuple[TestClient, FakeStore]) -> None:
    nodes = {n["id"]: n for n in fetch(api[0]).json()["nodes"]}

    assert nodes[PERSON]["degree"] == 2  # participated in, created
    assert nodes[NEW]["degree"] == 2  # created by, supersedes
    assert nodes[OLD]["degree"] == 1


def test_at_selects_the_moment_the_relations_are_read_for(
    api: tuple[TestClient, FakeStore],
) -> None:
    client, store = api

    fetch(client, at="2026-03-01T09:00:00+09:00")

    edge_query = next(params for query, params in store.calls if "type(r) IN" in query)
    assert edge_query["at"] == "2026-03-01T00:00:00+00:00"


def test_without_at_the_graph_is_read_as_of_now(api: tuple[TestClient, FakeStore]) -> None:
    client, store = api

    fetch(client)

    edge_query = next(params for query, params in store.calls if "type(r) IN" in query)
    assert edge_query["at"].endswith("+00:00")


def test_an_unknown_or_foreign_workspace_is_a_404(api: tuple[TestClient, FakeStore]) -> None:
    client, _ = api
    assert fetch(client, workspace=uuid4()).status_code == 404

    async def foreign() -> Any:
        yield FakeSession(uuid4())

    app.dependency_overrides[get_session] = foreign
    assert fetch(client).status_code == 404


def test_directory_graph_remains_available_when_neo4j_is_not_configured() -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

    async def session() -> Any:
        yield FakeSession(USER)

    app.dependency_overrides[get_session] = session
    try:
        response = fetch(TestClient(app))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["edges"] == []

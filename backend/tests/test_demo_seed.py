import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import demo_seed
from app.api.workspaces.review import ReviewUtterance
from app.core import config as config_module
from app.core.config import Settings
from app.modules.context_engine.application.context_store import state_from_record
from app.modules.context_engine.application.entity_resolution import entity_id
from app.modules.context_engine.infrastructure.models import Chunk, ContextStoreRecord
from app.modules.workspaces.infrastructure.models import Source, Workspace

OWNER = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE = UUID("00000000-0000-0000-0000-000000000002")


def plan() -> demo_seed.SeedPlan:
    fixture, digest = demo_seed.load_fixture()
    return demo_seed.build_plan(OWNER, WORKSPACE, fixture, digest)


def test_fixture_has_stable_ids_and_only_text_data() -> None:
    first, again = plan(), plan()
    assert first.counts() == {
        "people": 2,
        "projects": 1,
        "membership": 2,
        "sources": 3,
        "source_projects": 3,
        "source_people": 4,
        "chunks": 7,
        "contexts": 6,
        "context_store": 1,
        "graph_nodes": 7,
        "graph_edges": 8,
    }
    assert [item.id for item in first.sources] == [item.id for item in again.sources]
    assert all(source.content_type == "text/plain" for source in first.sources)
    assert all(
        source.review_state == "confirmed" for source in first.sources if source.kind == "meeting"
    )
    assert all(source.confirmed_snapshot for source in first.sources if source.kind == "meeting")
    assert all(chunk.embedding is None for chunk in first.chunks)
    assert all(person.email is None for person in first.people)
    assert all(item.source_id in {source.id for source in first.sources} for item in first.contexts)
    assert len(state_from_record(first.context_store).decisions) == 2
    assert all(
        ReviewUtterance.model_validate(item).text
        for source in first.sources
        if source.kind == "meeting"
        for item in source.review_utterances
    )
    canonical_person = entity_id(WORKSPACE, "Person", f"id:directory:person:{first.people[0].id}")
    assert str(canonical_person) in {node["id"] for node in first.graph_nodes}


class FakeSession:
    def __init__(self) -> None:
        self.rows: dict[tuple[type, UUID], object] = {}
        self.pending: list[object] = []
        self.commits = 0

    async def get(self, model: type, identifier: UUID, **kwargs: object) -> object | None:
        return self.rows.get((model, identifier))

    def add(self, row: object) -> None:
        self.pending.append(row)

    async def flush(self) -> None:
        for row in self.pending:
            self.rows[(type(row), row.id)] = row
        self.pending.clear()

    async def exec(self, statement: object) -> SimpleNamespace:
        stores = [row for (model, _), row in self.rows.items() if model is ContextStoreRecord]
        return SimpleNamespace(all=lambda: stores)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_does_not_update_existing_records() -> None:
    session = FakeSession()
    first = plan()
    added = await demo_seed.seed_postgres(session, first)
    assert added["sources"] == 3 and added["chunks"] == 7
    assert session.commits == 1
    existing = session.rows[(Source, first.sources[0].id)]
    existing.title = "Edited by an operator"
    second = plan()
    repeated = await demo_seed.seed_postgres(session, second)
    assert all(count == 0 for count in repeated.values())
    assert session.rows[(Source, first.sources[0].id)].title == "Edited by an operator"
    assert session.commits == 2


@pytest.mark.asyncio
async def test_seed_refuses_an_unrelated_workspace() -> None:
    session = FakeSession()
    session.rows[(Workspace, WORKSPACE)] = Workspace(id=WORKSPACE, owner_id=OWNER, name="real")
    with pytest.raises(demo_seed.SeedError, match="not this exact"):
        await demo_seed.seed_postgres(session, plan())
    assert session.commits == 0
    assert not any(model is Chunk for model, _ in session.rows)


def test_dry_run_never_executes_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    async def forbidden(_plan: demo_seed.SeedPlan) -> None:
        raise AssertionError("Dry run must not open a database")

    monkeypatch.setattr(demo_seed, "execute", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "demo_seed",
            "--owner",
            str(OWNER),
            "--workspace",
            str(WORKSPACE),
        ],
    )
    demo_seed.main()
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["counts"]["chunks"] == 7


@pytest.mark.asyncio
async def test_graph_seed_uses_create_only_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

    statements: list[tuple[str, dict]] = []

    class FakeGraph:
        async def verify_connectivity(self) -> None:
            pass

        async def execute(self, query: str, parameters: dict) -> list[dict]:
            statements.append((query, parameters))
            return []

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            neo4j_uri="bolt://example",
            neo4j_username="demo",
            neo4j_password=SecretStr("test"),
        ),
    )
    monkeypatch.setattr(Neo4jGraphStore, "from_settings", lambda: FakeGraph())
    await demo_seed.seed_graph(plan())
    assert statements[0][1]["workspace_id"] == str(WORKSPACE)
    assert "ON CREATE SET" in statements[1][0]
    assert all("ON CREATE SET" in query for query, _ in statements[1:])

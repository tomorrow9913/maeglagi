"""Offline clone contract: source is the configured persisted demo, never a fixture read."""

from collections import defaultdict
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import demo_clone, demo_seed
from app.api import demo
from app.auth.models import AuthUser
from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    ProviderCredential,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

PUBLIC_OWNER = uuid4()
PUBLIC_ID = uuid4()


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, plan):
        self.rows = defaultdict(list)
        self.pending = []
        self.commits = 0
        self.locks = 0
        self.original_ids = set()
        for model, items in (
            (Workspace, [plan.workspace]),
            (WorkspacePerson, plan.people),
            (WorkspaceProject, plan.projects),
            (ProjectMember, plan.membership),
            (Source, plan.sources),
            (SourceProject, plan.source_projects),
            (SourcePerson, plan.source_people),
            (Chunk, plan.chunks),
            (ContextRecord, plan.contexts),
            (ContextStoreRecord, [plan.context_store]),
        ):
            self.rows[model].extend(items)
            self.original_ids.update(row.id for row in items)
        self.rows[ProviderCredential].append(
            ProviderCredential(
                workspace_id=PUBLIC_ID,
                owner_id=PUBLIC_OWNER,
                provider="openai",
                encrypted_secret="do-not-copy",
                key_hint="xxxx",
            )
        )

    async def execute(self, query, parameters=None):
        assert "pg_advisory_xact_lock" in str(query)
        self.locks += 1

    async def get(self, model, identifier):
        return next((row for row in self.rows[model] if row.id == identifier), None)

    async def exec(self, statement):
        model = statement.column_descriptions[0]["entity"]
        workspace_id = next(
            value
            for key, value in statement.compile().params.items()
            if key.startswith("workspace_id")
        )
        return FakeResult([row for row in self.rows[model] if row.workspace_id == workspace_id])

    def add(self, row):
        self.pending.append(row)

    async def flush(self):
        for row in self.pending:
            self.rows[type(row)].append(row)
        self.pending.clear()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.pending.clear()
        for model, rows in self.rows.items():
            self.rows[model] = [row for row in rows if row.id in self.original_ids]


class GraphResult:
    async def single(self):
        return {"count": 0}


class GraphTx:
    def __init__(self, graph):
        self.graph = graph
        self.nodes = []
        self.edges = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def run(self, query, **params):
        if "RETURN count(n)" in query:
            return GraphResult()
        if "CREATE (n:Entity" in query:
            self.nodes.append(params["props"])
        if "CREATE (a)-[r:" in query:
            if self.graph.fail_write:
                raise RuntimeError("Neo4j write failed")
            self.edges.append((query, params))
        return GraphResult()

    async def commit(self):
        self.graph.writes += 1
        self.graph.cloned_nodes = self.nodes
        self.graph.cloned_edges = self.edges


class GraphConnection:
    def __init__(self, graph):
        self.graph = graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def begin_transaction(self):
        return GraphTx(self.graph)


class FakeGraph:
    def __init__(self, plan):
        self.plan = plan
        self._driver = self
        self.writes = 0
        self.cloned_nodes = []
        self.cloned_edges = []
        self.fail_write = False

    async def verify_connectivity(self):
        pass

    async def execute(self, query, parameters):
        if "RETURN properties(n)" in query:
            return [{"props": node} for node in self.plan.graph_nodes]
        if "RETURN a.id AS source" in query:
            return [
                {
                    "props": {
                        key: value
                        for key, value in edge.items()
                        if key not in {"source", "target", "kind"}
                    },
                    "source": edge["source"],
                    "target": edge["target"],
                    "kind": edge["kind"],
                }
                for edge in self.plan.graph_edges
            ]
        raise AssertionError(query)

    def session(self):
        return GraphConnection(self)


def state():
    fixture, digest = demo_seed.load_fixture()
    plan = demo_seed.build_plan(PUBLIC_OWNER, PUBLIC_ID, fixture, digest)
    return plan, FakeDb(plan), FakeGraph(plan)


@pytest.mark.asyncio
async def test_clone_preserves_history_and_creates_private_editable_draft():
    plan, db, graph = state()
    owner = uuid4()
    cloned, count = await demo_clone.clone_demo(db, graph, plan.workspace, owner)
    assert count == 4 and db.commits == 1 and db.locks == 1 and graph.writes == 1
    assert cloned.id == demo_clone.target_id(owner, PUBLIC_ID)
    assert cloned.owner_id == owner and cloned.model_settings == {}
    assert not [row for row in db.rows[ProviderCredential] if row.workspace_id == cloned.id]
    originals = [row for row in db.rows[Source] if row.workspace_id == PUBLIC_ID]
    copied = [row for row in db.rows[Source] if row.workspace_id == cloned.id]
    processed = [row for row in copied if row.status == "succeeded"]
    draft = next(row for row in copied if row.review_state == "awaiting_review")
    assert len(originals) == len(processed) == 3
    assert draft.title.endswith("편집 체험용 초안")
    assert draft.status == "awaiting_review" and draft.processing_stage == "awaiting_review"
    assert draft.confirmed_snapshot is None and draft.analysis_checkpoint is None
    assert draft.review_utterances and draft.project_id
    assert not [row for row in db.rows[Chunk] if row.source_id == draft.id]
    assert not [row for row in db.rows[ContextRecord] if row.source_id == draft.id]
    assert {row.owner_id for row in processed} == {owner}
    assert {row.id for row in processed}.isdisjoint({row.id for row in originals})
    assert all(row.confirmed_snapshot for row in processed if row.kind == "meeting")
    assert len([row for row in db.rows[Chunk] if row.workspace_id == cloned.id]) == 7
    assert len([row for row in db.rows[ContextRecord] if row.workspace_id == cloned.id]) == 6
    store = next(row for row in db.rows[ContextStoreRecord] if row.workspace_id == cloned.id)
    assert len(store.source_ids) == len(plan.context_store.source_ids)
    assert set(store.source_ids) <= {str(row.id) for row in processed}
    assert all(str(item["source_id"]) in store.source_ids for item in store.decisions)
    assert len(graph.cloned_nodes) == 7 and len(graph.cloned_edges) == 8
    assert all(node["workspace_id"] == str(cloned.id) for node in graph.cloned_nodes)
    assert all(
        node["source_id"] in {str(row.id) for row in processed} for node in graph.cloned_nodes
    )
    assert all(str(draft.id) not in node["source_ids"] for node in graph.cloned_nodes)
    person_ids = {str(row.id) for row in db.rows[WorkspacePerson] if row.workspace_id == cloned.id}
    assert all(item["personId"] in person_ids for item in draft.review_utterances)
    for source in processed:
        if source.kind != "meeting":
            continue
        assert all(item["personId"] in person_ids for item in source.review_utterances)
        snapshot = source.confirmed_snapshot
        assert all(item["id"] in person_ids for item in snapshot.get("people", []))
    assert all(
        str(row.project_id)
        in {str(p.id) for p in db.rows[WorkspaceProject] if p.workspace_id == cloned.id}
        for row in copied
        if row.project_id
    )


@pytest.mark.asyncio
async def test_retry_returns_own_workspace_without_replacing_edits():
    plan, db, graph = state()
    owner = uuid4()
    first, _ = await demo_clone.clone_demo(db, graph, plan.workspace, owner)
    first.name = "My edited title"
    own_source = next(row for row in db.rows[Source] if row.workspace_id == first.id)
    own_source.title = "My source edit"
    again, count = await demo_clone.clone_demo(db, None, plan.workspace, owner)
    assert again is first and again.name == "My edited title" and count == 4
    assert own_source.title == "My source edit" and graph.writes == 1 and db.commits == 1
    second_owner = uuid4()
    second, _ = await demo_clone.clone_demo(db, graph, plan.workspace, second_owner)
    assert second.id != first.id and second.owner_id == second_owner
    assert not {row.id for row in db.rows[Source] if row.workspace_id == first.id}.intersection(
        {row.id for row in db.rows[Source] if row.workspace_id == second.id}
    )


@pytest.mark.asyncio
async def test_missing_graph_or_binary_source_rejects_without_private_workspace():
    plan, db, graph = state()
    owner = uuid4()
    with pytest.raises(demo_clone.CloneUnavailable, match="graph database"):
        await demo_clone.clone_demo(db, None, plan.workspace, owner)
    assert await db.get(Workspace, demo_clone.target_id(owner, PUBLIC_ID)) is None
    plan.sources[0].content_type = "audio/wav"
    with pytest.raises(demo_clone.CloneUnavailable, match="normalized text"):
        await demo_clone.clone_demo(db, graph, plan.workspace, owner)
    assert await db.get(Workspace, demo_clone.target_id(owner, PUBLIC_ID)) is None


@pytest.mark.asyncio
async def test_failed_graph_transaction_rolls_back_private_sql_rows():
    plan, db, graph = state()
    graph.fail_write = True
    owner = uuid4()
    with pytest.raises(RuntimeError, match="Neo4j write failed"):
        await demo_clone.clone_demo(db, graph, plan.workspace, owner)
    target = demo_clone.target_id(owner, PUBLIC_ID)
    assert await db.get(Workspace, target) is None
    assert not [row for row in db.rows[Source] if row.workspace_id == target]
    assert db.commits == 0 and graph.writes == 0


def test_http_route_requires_user_and_returns_workspace_response():
    plan, db, graph = state()
    user = AuthUser(id=uuid4())
    from app.api.workspaces.graph import get_graph_store
    from app.auth import get_current_user
    from app.core.config import Settings, get_settings
    from app.core.database import get_session

    settings = Settings(
        _env_file=None,
        demo_workspace_id=str(PUBLIC_ID),
        supabase_url="https://example.test",
        supabase_publishable_key="test",
    )
    application = FastAPI()
    application.include_router(demo.router, prefix="/api/v1")
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = lambda: db
    application.dependency_overrides[get_graph_store] = lambda: graph
    with TestClient(application) as client:
        anonymous = client.post("/api/v1/demo/clone")
        assert anonymous.status_code == 401
        assert db.commits == 0
        application.dependency_overrides[get_current_user] = lambda: user
        response = client.post("/api/v1/demo/clone")
        assert response.status_code == 200
        assert response.json()["id"] == str(demo_clone.target_id(user.id, PUBLIC_ID))
        assert response.json()["sourceCount"] == 4

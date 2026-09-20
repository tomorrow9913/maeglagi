"""Owner checks and fixed, bounded graph reads for MCP knowledge tools."""

from uuid import uuid4

import pytest

from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord
from app.modules.retrieval.application.agent_knowledge import (
    AgentKnowledgeService,
    KnowledgeAccessError,
)
from app.modules.workspaces.infrastructure.models import Source, Workspace


class FakeSession:
    def __init__(self, workspace):
        self.workspace = workspace

    async def get(self, _model, _id):
        return self.workspace


class FakeGraphStore:
    def __init__(self):
        self.calls = []

    async def execute(self, query, params):
        self.calls.append((query, params))
        return [
            {
                "id": "entity-1",
                "kind": "Decision",
                "name": "Approved",
                "source_ids": ["source-1"],
                "superseded_by": None,
                "identifiers": ["private-ignored"],
            }
        ]


@pytest.mark.asyncio
async def test_graph_page_checks_owner_and_returns_only_safe_fields():
    alice, bob, workspace_id = uuid4(), uuid4(), uuid4()
    workspace = Workspace(id=workspace_id, owner_id=alice, name="Private")
    graph = FakeGraphStore()
    service = AgentKnowledgeService(FakeSession(workspace), graph)

    with pytest.raises(KnowledgeAccessError, match="workspace_not_found"):
        await service.graph_nodes(owner_id=bob, workspace_id=workspace_id)
    assert graph.calls == []

    nodes = await service.graph_nodes(owner_id=alice, workspace_id=workspace_id, limit=3, offset=2)
    assert nodes == {
        "available": True,
        "nodes": [
            {
                "id": "entity-1",
                "kind": "Decision",
                "name": "Approved",
                "sourceIds": ["source-1"],
                "supersededBy": None,
            }
        ],
        "offset": 2,
        "limit": 3,
    }
    query, params = graph.calls[0]
    assert "SKIP $offset LIMIT $limit" in query
    assert params == {"workspace_id": str(workspace_id), "offset": 2, "limit": 3}

    with pytest.raises(KnowledgeAccessError, match="invalid_page"):
        await service.graph_nodes(owner_id=alice, workspace_id=workspace_id, limit=51)


@pytest.mark.asyncio
async def test_disabled_graph_is_explicit_and_timeline_links_replacement():
    owner_id, workspace_id = uuid4(), uuid4()
    workspace = Workspace(id=workspace_id, owner_id=owner_id, name="Private")
    source = Source(
        workspace_id=workspace_id,
        owner_id=owner_id,
        kind="meeting",
        title="Review",
        object_path="owner/workspace/source.txt",
        content_type="text/plain",
        size_bytes=1,
    )
    older = ContextRecord(
        workspace_id=workspace_id,
        owner_id=owner_id,
        source_id=source.id,
        kind="decision",
        title="Old plan",
        body="We chose the old plan.",
        metadata_={"key": "decision:old-plan"},
    )
    successor = ContextRecord(
        workspace_id=workspace_id,
        owner_id=owner_id,
        source_id=source.id,
        kind="decision",
        title="New plan",
        body="We chose the new plan.",
        metadata_={"supersedes": "decision:old-plan"},
    )

    class Session(FakeSession):
        def __init__(self):
            super().__init__(workspace)
            self.results = [[(older, source)], [(successor.id, successor.metadata_)]]

        async def exec(self, _query):
            rows = self.results.pop(0)

            class Result:
                def all(self):
                    return rows

            return Result()

    service = AgentKnowledgeService(Session())
    assert await service.graph_nodes(owner_id=owner_id, workspace_id=workspace_id) == {
        "available": False,
        "nodes": [],
        "offset": 0,
        "limit": 20,
    }
    history = await service.timeline(owner_id=owner_id, workspace_id=workspace_id)
    assert history[0]["supersededBy"] == str(successor.id)


@pytest.mark.asyncio
async def test_context_store_reports_current_state():
    owner_id, workspace_id = uuid4(), uuid4()
    workspace = Workspace(id=workspace_id, owner_id=owner_id, name="Private")
    record = ContextStoreRecord(
        workspace_id=workspace_id,
        owner_id=owner_id,
        subject="Project",
        summary="Approved the next step",
        current_state="Ready",
        decisions=[{"title": "Proceed", "description": "Approved", "source_refs": ["quote"]}],
    )

    class Session(FakeSession):
        async def exec(self, _query):
            class Result:
                def first(self):
                    return record

            return Result()

    current = await AgentKnowledgeService(Session(workspace)).context_store(
        owner_id=owner_id, workspace_id=workspace_id
    )
    assert current["available"] is True
    assert current["decisions"][0]["sourceRefs"] == ["quote"]

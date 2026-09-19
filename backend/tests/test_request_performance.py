import asyncio
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.requests import Request

from app.api.workspaces.graph import get_graph_store
from app.api.workspaces.router import list_sources
from app.auth.models import AuthUser
from app.core.config import Settings
from app.main import create_app
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.infrastructure.models import (
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
)


def test_graph_driver_is_reused_within_app_and_closed_per_lifespan(monkeypatch: Any) -> None:
    stores = []

    class Store:
        def __init__(self) -> None:
            self.loop = asyncio.get_running_loop()
            self.closed = 0

        async def close(self) -> None:
            assert asyncio.get_running_loop() is self.loop
            self.closed += 1

    def create_store(cls: Any, settings: Settings) -> Store:
        assert settings.neo4j_enabled
        store = Store()
        stores.append(store)
        return store

    monkeypatch.setattr(Neo4jGraphStore, "from_settings", classmethod(create_store))
    settings = Settings(
        _env_file=None,
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="test",
        neo4j_password=SecretStr("test"),
    )

    for _ in range(2):
        application = create_app(settings)
        with TestClient(application):
            request = Request({"type": "http", "app": application})
            assert get_graph_store(request) is get_graph_store(request) is stores[-1]
            assert stores[-1].closed == 0
        assert stores[-1].closed == 1
        assert application.state.graph_store is None
    assert stores[0] is not stores[1]


@pytest.mark.asyncio
async def test_source_list_batches_associations_and_preserves_fallback() -> None:
    owner, workspace_id, first_project, fallback_project, person_id = (uuid4() for _ in range(5))
    workspace = Workspace(id=workspace_id, owner_id=owner, name="test")
    first = Source(
        workspace_id=workspace_id,
        owner_id=owner,
        kind="meeting",
        title="first",
        object_path="first",
        content_type="audio/mpeg",
        size_bytes=1,
        project_id=fallback_project,
    )
    second = Source(
        workspace_id=workspace_id,
        owner_id=owner,
        kind="document",
        title="second",
        object_path="second",
        content_type="text/plain",
        size_bytes=1,
        project_id=fallback_project,
    )
    rows = {
        Source: [first, second],
        SourceProject: [
            SourceProject(
                workspace_id=workspace_id,
                source_id=first.id,
                project_id=first_project,
                position=0,
            )
        ],
        SourcePerson: [
            SourcePerson(
                workspace_id=workspace_id,
                source_id=first.id,
                person_id=person_id,
                role="author",
            )
        ],
    }

    class Result:
        def __init__(self, values: list[Any]) -> None:
            self.values = values

        def all(self) -> list[Any]:
            return self.values

    class Session:
        queries = 0

        async def get(self, model: Any, identifier: Any) -> Workspace:
            assert model is Workspace and identifier == workspace_id
            return workspace

        async def exec(self, statement: Any) -> Result:
            self.queries += 1
            model = statement.column_descriptions[0]["entity"]
            return Result(rows[model])

    session = Session()
    result = await list_sources(workspace_id, AuthUser(id=str(owner)), session)

    assert session.queries == 3
    assert result[0].project_ids == [first_project]
    assert result[1].project_ids == [fallback_project]
    assert result[0].associations == [{"personId": str(person_id), "role": "author"}]
    assert result[1].associations == []
    assert result[0].has_recording is True

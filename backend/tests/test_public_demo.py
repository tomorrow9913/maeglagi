from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import demo
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.workspaces.infrastructure.models import Source, Workspace


@pytest.fixture
def demo_client():
    workspace = Workspace(name="Public demo", owner_id=uuid4())
    session = AsyncMock()
    session.get.return_value = workspace
    settings = Settings(demo_workspace_id=str(workspace.id))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client, workspace, session, settings
    app.dependency_overrides.clear()


def test_demo_disabled_without_explicit_public_workspace(demo_client):
    client, _, session, settings = demo_client
    settings.demo_workspace_id = ""
    response = client.get("/api/v1/demo/people")
    assert response.status_code == 503
    session.get.assert_not_awaited()


def test_demo_reads_only_server_selected_workspace(demo_client, monkeypatch):
    client, workspace, _, _ = demo_client
    handler = AsyncMock(return_value=[])
    monkeypatch.setattr(demo.directory, "list_people", handler)
    response = client.get(f"/api/v1/demo/people?workspaceId={uuid4()}")
    assert response.status_code == 200
    assert response.json() == []
    assert handler.call_args.args[0] == workspace.id
    assert handler.call_args.args[1].id == workspace.owner_id


def test_demo_rejects_private_source_even_for_same_owner(demo_client, monkeypatch):
    client, workspace, session, _ = demo_client
    private = Source(
        workspace_id=uuid4(),
        owner_id=workspace.owner_id,
        kind="document",
        title="Private",
        object_path="private.txt",
        content_type="text/plain",
        size_bytes=1,
    )
    session.get.side_effect = lambda model, identifier: workspace if model is Workspace else private
    handler = AsyncMock()
    monkeypatch.setattr(demo.source_content, "get_source_content", handler)
    response = client.get(f"/api/v1/demo/sources/{private.id}/content")
    assert response.status_code == 404
    handler.assert_not_awaited()


@pytest.mark.parametrize("path", ["people", "projects", "workspace", "sources", "ask"])
def test_demo_has_no_mutation_endpoints(demo_client, path):
    client, _, _, _ = demo_client
    response = client.post(f"/api/v1/demo/{path}", json={})
    assert response.status_code in (404, 405)


def test_demo_does_not_authenticate_private_routes(demo_client):
    client, workspace, _, settings = demo_client
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_publishable_key = SecretStr("public-test")
    response = client.get(f"/api/v1/workspaces/{workspace.id}/people")
    assert response.status_code == 401

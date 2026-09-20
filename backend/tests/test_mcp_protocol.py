"""Protocol and security checks through the official MCP SDK client."""

import asyncio
import json
from uuid import uuid4

import httpx2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.auth.models import AuthUser
from app.core.config import Settings
from app.main import create_app
from app.mcp.transport import MAX_MCP_REQUEST_BYTES


def _app(monkeypatch, principals):
    async def authenticate(token, settings):
        if token not in principals:
            raise HTTPException(401, "invalid")
        return AuthUser(id=principals[token])

    monkeypatch.setattr("app.auth.mcp.authenticate_mcp_token", authenticate)
    return create_app(
        Settings(
            _env_file=None,
            processing_executor="celery",
            pg_executor_enabled=False,
            cors_origins=["http://localhost:3000"],
        )
    )


async def _client(app, token):
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_sdk_initialize_list_call_resource_prompt_and_keyless_creation(monkeypatch):
    owner_id = uuid4()
    source_calls = []
    app = _app(monkeypatch, {"good": owner_id})

    class FakeService:
        async def list_workspaces(self, *, owner_id):
            return [{"id": str(owner_id), "name": "mine"}]

        async def create_workspace(self, *, owner_id, name):
            return {"id": str(owner_id), "name": name}

        async def media_download_url(self, *, owner_id, workspace_id, source_id):
            return {"url": "https://storage.example/signed?token=short-lived", "expiresAt": "soon"}

        async def create_text_source(self, **kwargs):
            source_calls.append(kwargs)
            return {"id": str(uuid4())}

    async def call(_settings, operation):
        return await operation(FakeService())

    monkeypatch.setattr("app.mcp.tools.workspaces.workflow_call", call)
    monkeypatch.setattr("app.mcp.tools.sources.workflow_call", call)

    class FakeKnowledge:
        def __init__(self, session, graph_store):
            assert graph_store is None

        async def lexical_search(self, *, owner_id, workspace_id, query, limit):
            return [{"sourceId": str(owner_id), "text": query, "limit": limit}]

        async def list_projects(self, *, owner_id, workspace_id, limit, offset):
            return [{"id": str(owner_id), "name": "project"}]

    monkeypatch.setattr(
        "app.modules.retrieval.application.agent_knowledge.AgentKnowledgeService",
        FakeKnowledge,
    )
    async with (
        app.router.lifespan_context(app),
        await _client(app, "good") as http,
        streamable_http_client("http://localhost/mcp", http_client=http) as streams,
        ClientSession(*streams) as client,
    ):
        initialized = await client.initialize()
        assert initialized.server_info.name == "maeglagi"
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert {"list_workspaces", "create_workspace", "submit_analysis"} <= tools.keys()
        assert tools["list_workspaces"].annotations.read_only_hint is True
        assert tools["create_workspace"].annotations.destructive_hint is False
        assert tools["submit_analysis"].annotations.destructive_hint is True
        assert tools["submit_analysis"].annotations.idempotent_hint is True
        assert "llm_api_key" not in tools["create_workspace"].input_schema["properties"]
        projects_schema = tools["create_text_source"].input_schema["properties"]["project_ids"]
        assert projects_schema["anyOf"][0]["maxItems"] == 50
        listed = await client.call_tool("list_workspaces")
        assert listed.structured_content == {"result": [{"id": str(owner_id), "name": "mine"}]}
        created = await client.call_tool("create_workspace", {"name": "Agent project"})
        assert created.structured_content == {"id": str(owner_id), "name": "Agent project"}
        searched = await client.call_tool(
            "lexical_search", {"workspace_id": str(uuid4()), "query": "decision"}
        )
        assert searched.structured_content["result"][0]["sourceId"] == str(owner_id)
        projects = await client.call_tool("list_projects", {"workspace_id": str(uuid4())})
        assert projects.structured_content["result"][0]["name"] == "project"
        media = await client.call_tool(
            "media_download_url", {"workspace_id": str(uuid4()), "source_id": str(uuid4())}
        )
        assert media.structured_content["url"].startswith("https://storage.example/signed")
        workspace_id, project_id = uuid4(), uuid4()
        source_args = {
            "workspace_id": str(workspace_id),
            "title": "Meeting notes",
            "text": "Approved the plan.",
        }
        associated = await client.call_tool(
            "create_text_source", {**source_args, "project_ids": [str(project_id)]}
        )
        assert associated.is_error is False
        assert source_calls[-1] == {
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "title": "Meeting notes",
            "text": "Approved the plan.",
            "kind": "document",
            "project_ids": [project_id],
        }
        unassociated = await client.call_tool("create_text_source", source_args)
        assert unassociated.is_error is False
        assert source_calls[-1]["project_ids"] is None
        invalid = await client.call_tool(
            "create_text_source", {**source_args, "project_ids": ["not-a-uuid"]}
        )
        assert invalid.is_error is True
        too_many = await client.call_tool(
            "create_text_source", {**source_args, "project_ids": [str(uuid4())] * 51}
        )
        assert too_many.is_error is True
        assert len(source_calls) == 2
        resources = await client.list_resources()
        assert any(str(item.uri) == "maeglagi://ontology/schema" for item in resources.resources)
        schema = await client.read_resource("maeglagi://ontology/schema")
        assert "Decision" in json.loads(schema.contents[0].text)["entityKinds"]
        prompts = await client.list_prompts()
        assert {item.name for item in prompts.prompts} == {
            "review_transcript",
            "grounded_analysis",
        }
        prompt = await client.get_prompt(
            "review_transcript", {"workspace_id": "w", "source_id": "s"}
        )
        assert "untrusted data" in prompt.messages[0].content.text


@pytest.mark.asyncio
async def test_auth_origin_host_and_principal_isolation(monkeypatch):
    alice, bob = uuid4(), uuid4()
    app = _app(monkeypatch, {"alice": alice, "bob": bob})

    class FakeService:
        async def list_workspaces(self, *, owner_id):
            return [{"id": str(owner_id), "name": "mine"}]

    async def call(_settings, operation):
        return await operation(FakeService())

    monkeypatch.setattr("app.mcp.tools.workspaces.workflow_call", call)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    accept = "application/json, text/event-stream"
    async with app.router.lifespan_context(app):
        async with await _client(app, "revoked") as http:
            invalid = await http.post("/mcp", json=request, headers={"Accept": accept})
            assert invalid.status_code == 401
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://localhost"
        ) as http:
            missing = await http.post("/mcp", json=request, headers={"Accept": accept})
            assert missing.status_code == 401
            get_without_token = await http.get("/mcp", headers={"Accept": "text/event-stream"})
            assert get_without_token.status_code == 401
            untrusted_origin = await http.post(
                "/mcp", json=request, headers={"Accept": accept, "Origin": "https://evil.example"}
            )
            assert untrusted_origin.status_code == 403
        async with await _client(app, "alice") as http:
            bad_origin = await http.post(
                "/mcp", json=request, headers={"Accept": accept, "Origin": "https://evil.example"}
            )
            assert bad_origin.status_code == 403
            accepted_origin = await http.post(
                "/mcp", json=request, headers={"Accept": accept, "Origin": "http://localhost:3000"}
            )
            assert accepted_origin.status_code == 200
            too_large = await http.post(
                "/mcp",
                content=b"x" * (MAX_MCP_REQUEST_BYTES + 1),
                headers={"Accept": accept, "Content-Type": "application/json"},
            )
            assert too_large.status_code == 413
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://evil.example",
            headers={"Authorization": "Bearer alice"},
        ) as http:
            bad_host = await http.post("/mcp", json=request, headers={"Accept": accept})
            assert bad_host.status_code == 421

        async def identity(token):
            async with (
                await _client(app, token) as http,
                streamable_http_client("http://localhost/mcp", http_client=http) as streams,
                ClientSession(*streams) as client,
            ):
                await client.initialize()
                result = await client.call_tool("list_workspaces")
                return result.structured_content["result"][0]["id"]

        assert await asyncio.gather(identity("alice"), identity("bob")) == [
            str(alice),
            str(bob),
        ]


@pytest.mark.asyncio
async def test_same_app_serves_mcp_across_sequential_lifespans(monkeypatch):
    alice, bob = uuid4(), uuid4()
    app = _app(monkeypatch, {"alice": alice, "bob": bob})

    class FakeService:
        async def list_workspaces(self, *, owner_id):
            return [{"id": str(owner_id)}]

    async def call(_settings, operation):
        return await operation(FakeService())

    monkeypatch.setattr("app.mcp.tools.workspaces.workflow_call", call)
    managers = []
    for token, owner_id in (("alice", alice), ("bob", bob)):
        async with app.router.lifespan_context(app):
            managers.append(app.state.mcp_server.session_manager)
            async with (
                await _client(app, token) as http,
                streamable_http_client("http://localhost/mcp", http_client=http) as streams,
                ClientSession(*streams) as client,
            ):
                await client.initialize()
                result = await client.call_tool("list_workspaces")
                assert result.structured_content == {"result": [{"id": str(owner_id)}]}

    assert managers[0] is not managers[1]


def test_same_app_testclient_restarts_mcp_transport(monkeypatch):
    app = _app(monkeypatch, {"good": uuid4()})
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    for _ in range(2):
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/mcp",
                json=initialize,
                headers={
                    "Authorization": "Bearer good",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["serverInfo"]["name"] == "maeglagi"

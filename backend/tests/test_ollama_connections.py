"""Workspace Ollama connections against the disposable local PostgreSQL service."""

import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces import credentials as credential_routes
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core import credentials as secrets
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.application.model_catalog import options_for_workspace
from app.modules.context_engine.application.model_roles import ModelRole
from app.modules.context_engine.application.provider import ChatResponse, ModelInfo
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.context_engine.infrastructure.ollama_adapter import OllamaAdapter
from app.modules.ingestion.application.pipeline import IngestionPipeline
from app.modules.workspaces.infrastructure.models import (
    ProviderCredential,
    Source,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)


@pytest.fixture
async def database(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    if urlparse(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Ollama connection tests require loopback PostgreSQL")
    schema = f"ollama_connections_{uuid4().hex}"
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": f"{schema},public,extensions"}}
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS extensions"))
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
        )
        # Create only this fixture's dependencies in its own schema. Other tests
        # may leave the public database at a different Alembic revision.
        await connection.run_sync(
            lambda sync: SQLModel.metadata.create_all(
                sync,
                tables=[
                    Workspace.__table__,
                    WorkspacePerson.__table__,
                    WorkspaceProject.__table__,
                    Source.__table__,
                    ProviderCredential.__table__,
                    Chunk.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner = uuid4()
    outsider = uuid4()
    current_owner = [owner]
    vault: dict[UUID, str] = {}

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def create_secret(session, *, secret, credential_id, workspace_id, provider):
        secret_id = uuid4()
        vault[secret_id] = secret
        return secret_id

    async def reveal_secret(session, *, secret_id):
        return vault[secret_id]

    async def update_secret(session, *, secret_id, secret):
        vault[secret_id] = secret

    async def delete_secret(session, *, secret_id):
        del vault[secret_id]

    monkeypatch.setattr(secrets.credential_vault, "create", create_secret)
    monkeypatch.setattr(secrets.credential_vault, "reveal", reveal_secret)
    monkeypatch.setattr(secrets.credential_vault, "update", update_secret)
    monkeypatch.setattr(secrets.credential_vault, "delete", delete_secret)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=str(current_owner[0]), metadata={}
    )
    try:
        yield factory, owner, outsider, current_owner, vault
    finally:
        app.dependency_overrides.clear()
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_boundary_base_url_and_key_rotation(database, monkeypatch) -> None:
    factory, owner, outsider, current_owner, vault = database
    workspace = Workspace(owner_id=owner, name="Ollama connection")
    async with factory() as session:
        session.add(workspace)
        await session.commit()

    async def validate(provider: str, key: str, base_url: str | None = None):
        return (base_url != "https://bad.example", "Connection rejected")

    monkeypatch.setattr(credential_routes, "validate_provider_credential", validate)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        path = f"/api/v1/workspaces/{workspace.id}/provider-credentials"
        added = await client.post(
            path,
            json={
                "provider": "ollama",
                "label": "private",
                "baseUrl": "https://one.example/",
                "apiKey": "secret-one",
            },
        )
        assert added.status_code == 201, added.text
        payload = added.json()
        credential_id = payload["id"]
        assert payload["baseUrl"] == "https://one.example"
        assert "secret-one" not in added.text
        assert len(vault) == 1

        current_owner[0] = outsider
        assert (await client.get(path)).status_code == 404
        assert (
            await client.put(f"{path}/{credential_id}", json={"baseUrl": "https://other.example"})
        ).status_code == 404
        current_owner[0] = owner

        rejected = await client.put(
            f"{path}/{credential_id}",
            json={
                "baseUrl": "https://bad.example",
                "apiKey": "secret-two",
            },
        )
        assert rejected.status_code == 422
        assert next(iter(vault.values())) == "secret-one"
        assert (await client.get(path)).json()[0]["baseUrl"] == "https://one.example"

        changed = await client.put(
            f"{path}/{credential_id}", json={"baseUrl": "https://two.example"}
        )
        assert changed.status_code == 200
        assert changed.json()["baseUrl"] == "https://two.example"
        assert next(iter(vault.values())) == "secret-one"

        cleared = await client.put(f"{path}/{credential_id}", json={"apiKey": ""})
        assert cleared.status_code == 200
        assert cleared.json()["keyHint"] == "none"
        assert vault == {}

        short_key = await client.put(f"{path}/{credential_id}", json={"apiKey": "Q9"})
        assert short_key.status_code == 200
        assert short_key.json()["keyHint"] == "configured"
        assert '"Q9"' not in short_key.text


@pytest.mark.asyncio
async def test_duplicate_model_names_route_to_selected_credential(database, monkeypatch) -> None:
    factory, owner, _, _, vault = database
    workspace = Workspace(owner_id=owner, name="Two servers")
    first = ProviderCredential(
        workspace_id=workspace.id,
        owner_id=owner,
        provider="ollama",
        label="first",
        base_url="https://first.example",
        key_hint="local",
        is_default=True,
    )
    second = ProviderCredential(
        workspace_id=workspace.id,
        owner_id=owner,
        provider="ollama",
        label="second",
        base_url="https://second.example",
        key_hint="set",
        vault_secret_id=uuid4(),
    )
    vault[second.vault_secret_id] = "private-key"
    async with factory() as session:
        session.add(workspace)
        await session.flush()
        session.add(first)
        session.add(second)
        await session.commit()

    async def models(self: OllamaAdapter, api_key: str):
        return [ModelInfo(id="same:latest", roles=("answer", "extraction"))]

    monkeypatch.setattr(OllamaAdapter, "list_model_infos", models)
    async with factory() as session:
        options = await options_for_workspace(session, workspace.id, owner, "ollama")
        assert [item.credential_id for item in options[ModelRole.ANSWER]] == [first.id, second.id]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        choice = await client.put(
            f"/api/v1/workspaces/{workspace.id}/ai/models",
            json={
                "selections": {
                    "answer": {
                        "provider": "ollama",
                        "model": "same:latest",
                        "credentialId": str(second.id),
                    }
                }
            },
        )
        assert choice.status_code == 200, choice.text
    async with factory() as session:
        stored = await session.get(Workspace, workspace.id)
        assert stored.model_settings["answer"]["credentialId"] == str(second.id)
        provider = await IngestionPipeline().provider_with_model(
            session, workspace_id=workspace.id, owner_id=owner, role=ModelRole.ANSWER
        )
        assert provider.adapter.base_url == "https://second.example"
        assert provider.api_key == "private-key"
        assert provider.model == "same:latest"
        credentials = (
            await session.exec(
                select(ProviderCredential).where(ProviderCredential.workspace_id == workspace.id)
            )
        ).all()
        assert len(credentials) == 2

    calls = []

    async def chat(self: OllamaAdapter, request, api_key: str):
        calls.append((self.base_url, api_key))
        return ChatResponse(text="ok", model=request.model, provider="ollama")

    monkeypatch.setattr(OllamaAdapter, "chat", chat)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/workspaces/{workspace.id}/ai/chat",
            json={
                "provider": "ollama",
                "model": "same:latest",
                "credentialId": str(second.id),
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "ok"
        assert calls == [("https://second.example", "private-key")]


@pytest.mark.asyncio
async def test_saved_account_connection_reused_across_workspaces(database, monkeypatch) -> None:
    factory, owner, outsider, current_owner, _ = database

    async def validate(self: OllamaAdapter, api_key: str):
        return True, "ok"

    async def models(self: OllamaAdapter, api_key: str):
        return [ModelInfo(id="local:latest", roles=("answer", "extraction"))]

    monkeypatch.setattr(OllamaAdapter, "validate_credential", validate)
    monkeypatch.setattr(OllamaAdapter, "list_model_infos", models)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/provider-credentials",
            json={
                "provider": "ollama",
                "label": "my server",
                "baseUrl": "https://owned.example",
            },
        )
        assert created.status_code == 201, created.text
        credential_id = created.json()["id"]
        assert created.json()["baseUrl"] == "https://owned.example"

        preview = await client.post(
            "/api/v1/llm-keys/models",
            json={
                "credentialId": credential_id,
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["roles"][0]["options"][0]["credentialId"] == credential_id

        workspaces = []
        for name in ("one", "two"):
            response = await client.post(
                "/api/v1/workspaces",
                json={
                    "name": name,
                    "credentialId": credential_id,
                },
            )
            assert response.status_code == 201, response.text
            workspaces.append(response.json()["id"])
        assert len((await client.get("/api/v1/provider-credentials")).json()) == 1
        assert (
            await client.delete(f"/api/v1/provider-credentials/{credential_id}")
        ).status_code == 409

        async with factory() as session:
            first = await session.get(Workspace, UUID(workspaces[0]))
            second = await session.get(Workspace, UUID(workspaces[1]))
            assert first.model_settings["answer"]["credentialId"] == credential_id
            assert second.model_settings["answer"]["credentialId"] == credential_id
            await session.delete(first)
            await session.commit()
            saved = await session.get(ProviderCredential, UUID(credential_id))
            assert saved is not None and saved.owner_id == owner
        assert (
            await client.delete(f"/api/v1/provider-credentials/{credential_id}")
        ).status_code == 409

        current_owner[0] = outsider
        assert (await client.get("/api/v1/provider-credentials")).json() == []
        assert (
            await client.put(
                f"/api/v1/provider-credentials/{credential_id}",
                json={"baseUrl": "https://x.example"},
            )
        ).status_code == 404
        assert (
            await client.post("/api/v1/llm-keys/models", json={"credentialId": credential_id})
        ).status_code == 404
        denied = await client.post(
            "/api/v1/workspaces",
            json={
                "name": "foreign",
                "credentialId": credential_id,
            },
        )
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_deleting_inline_workspace_retains_account_connection(database, monkeypatch) -> None:
    factory, owner, _, _, vault = database

    async def validate(self: OllamaAdapter, api_key: str):
        return True, "ok"

    async def models(self: OllamaAdapter, api_key: str):
        return [ModelInfo(id="local:latest", roles=("answer", "extraction"))]

    monkeypatch.setattr(OllamaAdapter, "validate_credential", validate)
    monkeypatch.setattr(OllamaAdapter, "list_model_infos", models)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/workspaces",
            json={
                "name": "inline",
                "llmProvider": "ollama",
                "llmBaseUrl": "https://inline.example",
                "llmApiKey": "inline-secret",
            },
        )
        assert response.status_code == 201, response.text
        workspace_id = UUID(response.json()["id"])
        listed = (await client.get("/api/v1/provider-credentials")).json()
        assert len(listed) == 1
        credential_id = UUID(listed[0]["id"])
    async with factory() as session:
        credential = await session.get(ProviderCredential, credential_id)
        assert credential.workspace_id == workspace_id
        await session.delete(await session.get(Workspace, workspace_id))
        await session.commit()
        await session.refresh(credential)
        assert credential.workspace_id is None
        assert credential.owner_id == owner
        assert credential.base_url == "https://inline.example"
        assert vault[credential.vault_secret_id] == "inline-secret"

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mcp_tokens import TokenCreate, router
from app.auth import mcp
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings
from app.core.database import get_session


@pytest.fixture
async def token_sessions(monkeypatch):
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("local PostgreSQL required")
    schema = "test_mcp_tokens_" + uuid4().hex
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(lambda sync: mcp.McpToken.__table__.create(sync))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp, "session_factory", factory)
    yield factory
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def test_issue_authenticate_list_revoke_and_owner_boundary(token_sessions):
    owner, other = uuid4(), uuid4()
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    user = AuthUser(id=owner)

    async def session_dependency():
        async with token_sessions() as session:
            yield session

    application.dependency_overrides[get_session] = session_dependency
    application.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="http://test"
    ) as client:
        issued = await client.post("/api/v1/mcp-tokens", json={"label": "내 에이전트"})
        assert issued.status_code == 201
        assert issued.headers["cache-control"] == "no-store"
        payload = issued.json()
        secret = payload["token"]
        identifier = payload["item"]["id"]
        assert mcp.TOKEN_PATTERN.fullmatch(secret)
        assert payload["item"]["tokenHint"] == secret[-6:]
        async with token_sessions() as session:
            saved = (await session.exec(select(mcp.McpToken))).one()
            assert saved.token_hash == mcp.token_digest(secret)
            assert secret not in str(saved.model_dump())
        authenticated = await mcp.authenticate_mcp_token(secret, Settings(_env_file=None))
        assert authenticated.id == owner
        listed = await client.get("/api/v1/mcp-tokens")
        assert secret not in listed.text and "token_hash" not in listed.text
        assert listed.json()["items"][0]["lastUsedAt"] is not None
        user = AuthUser(id=other)
        assert (await client.get("/api/v1/mcp-tokens")).json() == {"items": []}
        assert (await client.delete(f"/api/v1/mcp-tokens/{identifier}")).status_code == 404
        user = AuthUser(id=owner)
        assert (await client.delete(f"/api/v1/mcp-tokens/{identifier}")).status_code == 204
        assert (await client.delete(f"/api/v1/mcp-tokens/{identifier}")).status_code == 204
        assert (await client.get("/api/v1/mcp-tokens")).json() == {"items": []}
        with pytest.raises(HTTPException) as exc:
            await mcp.authenticate_mcp_token(secret, Settings(_env_file=None))
        assert exc.value.status_code == 401


async def test_expiry_and_active_token_limit(token_sessions):
    owner = uuid4()
    async with token_sessions() as session:
        item, secret = await mcp.issue_token(session, owner, "expires")
        item.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(item)
        await session.commit()
    with pytest.raises(HTTPException) as exc:
        await mcp.authenticate_mcp_token(secret, Settings(_env_file=None))
    assert exc.value.status_code == 401
    async with token_sessions() as session:
        for index in range(mcp.MAX_ACTIVE_TOKENS):
            await mcp.issue_token(session, owner, str(index))
        with pytest.raises(HTTPException) as exc:
            await mcp.issue_token(session, owner, "over limit")
        assert exc.value.status_code == 409


async def test_custom_lifetime_is_persisted_and_enforced(token_sessions):
    owner = uuid4()
    before = datetime.now(UTC)
    async with token_sessions() as session:
        item, secret = await mcp.issue_token(session, owner, "short lived", 7)
        assert before + timedelta(days=7) <= item.expires_at
        assert item.expires_at <= datetime.now(UTC) + timedelta(days=7)
        item.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(item)
        await session.commit()
    with pytest.raises(HTTPException) as exc:
        await mcp.authenticate_mcp_token(secret, Settings(_env_file=None))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("days", [0, 366, -1, 1.5, "forever", True])
def test_invalid_lifetimes_rejected_by_request_schema(days):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TokenCreate.model_validate({"label": "agent", "expiresInDays": days})


def test_legacy_request_defaults_to_90_days():
    assert TokenCreate.model_validate({"label": "agent"}).expires_in_days == 90


@pytest.mark.parametrize("value", ["", "supabase-jwt", "mgmcp_" + "a" * 42, "mgmcp_" + "√" * 43])
async def test_malformed_tokens_rejected_without_database(monkeypatch, value):
    def forbidden():
        pytest.fail("malformed token reached database")

    monkeypatch.setattr(mcp, "session_factory", forbidden)
    with pytest.raises(HTTPException) as exc:
        await mcp.authenticate_mcp_token(value, Settings(_env_file=None))
    assert exc.value.status_code == 401

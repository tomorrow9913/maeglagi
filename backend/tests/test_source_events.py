"""Authenticated source SSE snapshots and short polling sessions."""

import json
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces import source_events as events
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.main import create_app
from app.modules.workspaces.infrastructure.models import Source, Workspace

OWNER, OTHER, WORKSPACE = uuid4(), uuid4(), uuid4()
SOURCE_A, SOURCE_B = uuid4(), uuid4()


def payload(source_id: UUID, status: str, *, progress: float = 0.0) -> str:
    return JobResponse(
        id=source_id,
        source_id=source_id,
        source_kind="meeting",
        transcript_source="server",
        status=status,
        progress=progress,
        stage="awaiting_review" if status == "awaiting_review" else "uploaded",
        error_message="STT failed" if status == "failed" else None,
    ).model_dump_json(by_alias=True)


class Request:
    disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.asyncio
async def test_snapshot_changes_and_terminal_states_without_duplicate_emits(monkeypatch) -> None:
    initial = {
        SOURCE_A: payload(SOURCE_A, "queued"),
        SOURCE_B: payload(SOURCE_B, "queued"),
    }
    snapshots = [
        initial,
        {
            SOURCE_A: payload(SOURCE_A, "awaiting_review", progress=0.45),
            SOURCE_B: initial[SOURCE_B],
        },
        {
            SOURCE_A: payload(SOURCE_A, "awaiting_review", progress=0.45),
            SOURCE_B: payload(SOURCE_B, "failed"),
        },
        {
            SOURCE_A: payload(SOURCE_A, "succeeded", progress=1),
            SOURCE_B: payload(SOURCE_B, "failed"),
        },
    ]
    calls = []

    async def read(workspace_id, owner_id, source_ids):
        calls.append((workspace_id, owner_id, source_ids))
        return snapshots.pop(0) if snapshots else snapshots_last

    snapshots_last = snapshots[-1]
    monkeypatch.setattr(events, "_read_jobs", read)
    clock = Clock()
    frames = [
        frame
        async for frame in events._stream_events(
            Request(),
            WORKSPACE,
            OWNER,
            [SOURCE_A, SOURCE_B],
            initial,
            poll_seconds=2,
            heartbeat_seconds=15,
            stream_seconds=11,
            now=clock.now,
            sleep=clock.sleep,
        )
    ]
    jobs = [
        json.loads(frame.split("data: ", 1)[1])
        for frame in frames
        if frame.startswith("event: job")
    ]
    assert [job["status"] for job in jobs] == [
        "queued",
        "queued",
        "awaiting_review",
        "failed",
        "succeeded",
    ]
    assert jobs[0]["sourceId"] == str(SOURCE_A)
    assert jobs[3]["errorMessage"] == "STT failed"
    assert len(calls) == 5
    assert all(call == (WORKSPACE, OWNER, [SOURCE_A, SOURCE_B]) for call in calls)


@pytest.mark.asyncio
async def test_heartbeat_lifetime_and_disconnect_cleanup(monkeypatch) -> None:
    initial = {SOURCE_A: payload(SOURCE_A, "queued")}
    calls = []

    async def read(*args):
        calls.append(args)
        return initial

    monkeypatch.setattr(events, "_read_jobs", read)
    clock = Clock()
    request = Request()
    frames = [
        frame
        async for frame in events._stream_events(
            request,
            WORKSPACE,
            OWNER,
            [SOURCE_A],
            initial,
            poll_seconds=5,
            heartbeat_seconds=3,
            stream_seconds=10,
            now=clock.now,
            sleep=clock.sleep,
        )
    ]
    assert frames.count(": heartbeat\n\n") == 3
    assert sum(frame.startswith("event: job") for frame in frames) == 1
    assert clock.value == 10

    clock = Clock()
    stream = events._stream_events(
        request,
        WORKSPACE,
        OWNER,
        [SOURCE_A],
        initial,
        poll_seconds=2,
        heartbeat_seconds=15,
        stream_seconds=55,
        now=clock.now,
        sleep=clock.sleep,
    )
    assert (await anext(stream)).startswith("event: job")
    prior_reads = len(calls)
    request.disconnected = True
    assert [frame async for frame in stream] == []
    assert len(calls) == prior_reads
    assert clock.value == 0


class Session:
    def __init__(self, *, workspace_owner: UUID = OWNER, rows: list[tuple] | None = None) -> None:
        self.workspace = Workspace(id=WORKSPACE, owner_id=workspace_owner, name="Test")
        self.rows = rows or []

    async def get(self, model, identifier):
        return self.workspace if model is Workspace and identifier == WORKSPACE else None

    async def exec(self, statement):
        return self.rows


def source_row(source_id: UUID) -> tuple:
    return (source_id, "meeting", "server", "queued", "server", 0.0, "uploaded", None)


@pytest.mark.asyncio
async def test_each_poll_closes_database_session_before_sleep(monkeypatch) -> None:
    active = 0
    opened = 0

    @asynccontextmanager
    async def factory():
        nonlocal active, opened
        active += 1
        opened += 1
        try:
            yield Session(rows=[source_row(SOURCE_A)])
        finally:
            active -= 1

    monkeypatch.setattr(events, "session_factory", factory)
    clock = Clock()

    async def sleep(seconds: float) -> None:
        assert active == 0
        await clock.sleep(seconds)

    initial = {SOURCE_A: payload(SOURCE_A, "queued")}
    frames = [
        frame
        async for frame in events._stream_events(
            Request(),
            WORKSPACE,
            OWNER,
            [SOURCE_A],
            initial,
            poll_seconds=2,
            heartbeat_seconds=15,
            stream_seconds=5,
            now=clock.now,
            sleep=sleep,
        )
    ]
    assert opened == 2
    assert active == 0
    assert len(frames) == 1


def test_http_auth_subscription_bounds_and_preheader_ownership(monkeypatch) -> None:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        supabase_url="https://auth.example",
        supabase_publishable_key=SecretStr("test-key"),
    )
    route = f"/api/v1/workspaces/{WORKSPACE}/source-events"
    with TestClient(app) as client:
        assert client.get(route, params={"source_ids": str(SOURCE_A)}).status_code == 401

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=OWNER)
    active = 0
    sessions = []

    @asynccontextmanager
    async def factory():
        nonlocal active
        active += 1
        try:
            yield sessions.pop(0)
        finally:
            active -= 1

    monkeypatch.setattr(events, "session_factory", factory)
    with TestClient(app) as client:
        assert client.get(route).status_code == 422
        assert client.get(route, params={"source_ids": "invalid"}).status_code == 422
        too_many = ",".join(str(uuid4()) for _ in range(101))
        assert client.get(route, params={"source_ids": too_many}).status_code == 422
        assert client.get(route, params={"source_ids": f"{SOURCE_A},{SOURCE_A}"}).status_code == 422

        sessions.append(Session(workspace_owner=OTHER))
        assert client.get(route, params={"source_ids": str(SOURCE_A)}).status_code == 404
        assert active == 0
        sessions.append(Session(rows=[source_row(SOURCE_A)]))
        assert client.get(route, params={"source_ids": f"{SOURCE_A},{SOURCE_B}"}).status_code == 404
        assert active == 0

        async def once(request, workspace_id, owner_id, source_ids, initial):
            assert active == 0
            yield events._job_event(initial[source_ids[0]])

        monkeypatch.setattr(events, "_stream_events", once)
        sessions.append(Session(rows=[source_row(SOURCE_A)]))
        response = client.get(route, params={"source_ids": str(SOURCE_A)})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        assert json.loads(response.text.split("data: ", 1)[1])["sourceId"] == str(SOURCE_A)
        assert active == 0


@pytest.mark.asyncio
async def test_initial_response_uses_job_schema_and_closes_session(monkeypatch) -> None:
    active = 0

    @asynccontextmanager
    async def factory():
        nonlocal active
        active += 1
        try:
            yield Session(rows=[source_row(SOURCE_A)])
        finally:
            active -= 1

    monkeypatch.setattr(events, "session_factory", factory)
    response = await events.source_events(WORKSPACE, str(SOURCE_A), Request(), AuthUser(id=OWNER))
    assert active == 0
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    stream = response.body_iterator
    frame = await anext(stream)
    assert frame.startswith("event: job\ndata: ")
    job = json.loads(frame.split("data: ", 1)[1])
    assert job == {
        "id": str(SOURCE_A),
        "sourceId": str(SOURCE_A),
        "sourceKind": "meeting",
        "transcriptSource": "server",
        "analysisMode": "server",
        "status": "queued",
        "progress": 0.0,
        "stage": "uploaded",
        "errorMessage": None,
    }
    await stream.aclose()


@pytest.mark.asyncio
async def test_real_postgres_query_excludes_other_workspace_sources() -> None:
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Source event integration test requires a loopback PostgreSQL host")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    owner, other = uuid4(), uuid4()
    owned_workspace = Workspace(owner_id=owner, name="Owned")
    foreign_workspace = Workspace(owner_id=other, name="Foreign")
    owned_source = Source(
        workspace_id=owned_workspace.id,
        owner_id=owner,
        kind="document",
        title="owned.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
    )
    foreign_source = Source(
        workspace_id=foreign_workspace.id,
        owner_id=other,
        kind="document",
        title="foreign.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS extensions"))
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
            )
            await connection.execute(text("SET search_path TO public, extensions"))
            await connection.run_sync(SQLModel.metadata.create_all)
        async with factory() as session:
            session.add(owned_workspace)
            session.add(foreign_workspace)
            await session.flush()
            session.add(owned_source)
            session.add(foreign_source)
            await session.commit()
            found = await events._load_jobs(
                session,
                owned_workspace.id,
                owner,
                [owned_source.id, foreign_source.id],
            )
            assert set(found) == {owned_source.id}
    finally:
        async with factory() as session:
            for item in (owned_source, foreign_source, owned_workspace, foreign_workspace):
                await session.delete(item)
            await session.commit()
        await engine.dispose()

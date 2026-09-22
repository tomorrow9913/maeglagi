"""Transactional source-event fanout and authenticated SSE snapshots."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
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
from app.api.workspaces.source_event_broker import (
    QUEUE_SIZE,
    SourceEventBroker,
    SourceEventKey,
    SourceSubscription,
)
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

    def __init__(self, broker=None):
        self.app = SimpleNamespace(state=SimpleNamespace(source_event_broker=broker))

    async def is_disconnected(self) -> bool:
        return self.disconnected


class FakeBroker:
    healthy = True

    def __init__(self):
        self.subscriptions = set()

    def subscribe(self, owner_id, workspace_id, source_ids):
        subscriber = SourceSubscription(owner_id, workspace_id, frozenset(source_ids))
        self.subscriptions.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        self.subscriptions.discard(subscriber)


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
async def test_event_stream_deduplicates_redelivery_and_resets_on_reconnect(monkeypatch) -> None:
    broker = FakeBroker()
    subscriber = broker.subscribe(OWNER, WORKSPACE, [SOURCE_A])
    current = {SOURCE_A: payload(SOURCE_A, "awaiting_review", progress=0.45)}
    calls = []

    async def read(workspace_id, owner_id, source_ids):
        calls.append((workspace_id, owner_id, source_ids))
        return current.copy()

    monkeypatch.setattr(events, "_read_jobs", read)
    stream = events._stream_events(
        Request(broker),
        WORKSPACE,
        OWNER,
        [SOURCE_A],
        {SOURCE_A: payload(SOURCE_A, "queued")},
        subscriber,
        broker,
        heartbeat_seconds=1,
        stream_seconds=5,
    )
    assert json.loads((await anext(stream)).split("data: ", 1)[1])["status"] == "queued"
    key = SourceEventKey(OWNER, WORKSPACE, SOURCE_A)
    subscriber.queue.put_nowait(key)
    assert json.loads((await anext(stream)).split("data: ", 1)[1])["status"] == "awaiting_review"

    # A second notification for the same committed state must not emit another job.
    subscriber.queue.put_nowait(key)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.02)
    assert not pending.done()
    current[SOURCE_A] = payload(SOURCE_A, "failed")
    subscriber.queue.put_nowait(key)
    assert json.loads((await pending).split("data: ", 1)[1])["status"] == "failed"
    assert calls == [(WORKSPACE, OWNER, [SOURCE_A])] * 3

    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    subscriber.reset()
    with pytest.raises(StopAsyncIteration):
        await pending
    assert not broker.subscriptions


@pytest.mark.asyncio
async def test_idle_stream_heartbeats_without_source_reads(monkeypatch) -> None:
    broker = FakeBroker()
    subscriber = broker.subscribe(OWNER, WORKSPACE, [SOURCE_A])

    async def unexpected_read(*_args):
        pytest.fail("Idle SSE must not poll Source")

    monkeypatch.setattr(events, "_read_jobs", unexpected_read)
    frames = [
        frame
        async for frame in events._stream_events(
            Request(broker),
            WORKSPACE,
            OWNER,
            [SOURCE_A],
            {SOURCE_A: payload(SOURCE_A, "queued")},
            subscriber,
            broker,
            heartbeat_seconds=0.01,
            stream_seconds=0.035,
        )
    ]
    assert frames[0].startswith("event: job")
    assert ": heartbeat\n\n" in frames[1:]
    assert not broker.subscriptions


@pytest.mark.asyncio
async def test_broker_fanout_filters_owner_workspace_and_source_and_bounds_queues() -> None:
    settings = Settings(
        _env_file=None,
        source_events_listener_database_url=SecretStr("postgresql://user:password@localhost/db"),
    )
    broker = SourceEventBroker(settings)
    second_process = SourceEventBroker(settings)
    owned = SourceSubscription(OWNER, WORKSPACE, frozenset({SOURCE_A}))
    other_owner = SourceSubscription(OTHER, WORKSPACE, frozenset({SOURCE_A}))
    other_workspace = SourceSubscription(OWNER, uuid4(), frozenset({SOURCE_A}))
    other_source = SourceSubscription(OWNER, WORKSPACE, frozenset({SOURCE_B}))
    broker._subscribers.update({owned, other_owner, other_workspace, other_source})
    second_client = SourceSubscription(OWNER, WORKSPACE, frozenset({SOURCE_A}))
    second_process._subscribers.add(second_client)

    class Connection:
        async def fetchval(self, query, message_id):
            assert message_id == 7
            return json.dumps(
                {
                    "owner_id": str(OWNER),
                    "workspace_id": str(WORKSPACE),
                    "source_id": str(SOURCE_A),
                }
            )

    broker._connection = Connection()
    second_process._connection = Connection()
    await asyncio.gather(broker._dispatch("7"), second_process._dispatch("7"))
    assert owned.queue.get_nowait() == SourceEventKey(OWNER, WORKSPACE, SOURCE_A)
    assert second_client.queue.get_nowait() == SourceEventKey(OWNER, WORKSPACE, SOURCE_A)
    assert all(item.queue.empty() for item in (other_owner, other_workspace, other_source))
    for _ in range(QUEUE_SIZE + 1):
        await broker._dispatch("7")
    assert owned.queue.qsize() == 1
    assert owned.queue.get_nowait() is None  # overflow forces an authoritative resnapshot

    class PrunedConnection:
        async def fetchval(self, query, message_id):
            return None

    broker._connection = PrunedConnection()
    await broker._dispatch("8")
    assert all(
        item.queue.get_nowait() is None
        for item in (owned, other_owner, other_workspace, other_source)
    )


@pytest.mark.asyncio
async def test_listener_termination_requests_reconnect_resync() -> None:
    broker = SourceEventBroker(
        Settings(
            _env_file=None,
            source_events_listener_database_url=SecretStr(
                "postgresql://user:password@localhost/db"
            ),
        )
    )
    subscriber = SourceSubscription(OWNER, WORKSPACE, frozenset({SOURCE_A}))
    broker._subscribers.add(subscriber)
    broker._notifications.put_nowait("5")
    broker._terminated(None)
    assert broker._notifications.get_nowait() is None
    broker._reset_subscribers()
    assert subscriber.queue.get_nowait() is None
    # A new subscription after reconnect starts with a fresh Source snapshot.
    broker.healthy = True
    replacement = broker.subscribe(OWNER, WORKSPACE, [SOURCE_A])
    assert replacement.queue.empty()


def test_listener_uses_session_database_url_and_rejects_transaction_pooler() -> None:
    fallback = SourceEventBroker(
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://user:password@localhost:5432/db",
        )
    )
    assert fallback._dsn == "postgresql://user:password@localhost:5432/db"
    with pytest.raises(RuntimeError, match="6543"):
        SourceEventBroker(
            Settings(
                _env_file=None,
                source_events_listener_database_url=SecretStr(
                    "postgresql://user:password@pooler.example:6543/db"
                ),
            )
        )


@pytest.mark.asyncio
async def test_listener_start_fails_explicitly_without_queue(monkeypatch) -> None:
    broker = SourceEventBroker(
        Settings(
            _env_file=None,
            source_events_listener_database_url=SecretStr(
                "postgresql://user:password@localhost/db"
            ),
        )
    )

    async def unavailable():
        raise RuntimeError("missing extension")

    monkeypatch.setattr(broker, "_connect", unavailable)
    with pytest.raises(RuntimeError, match="pgmq migration"):
        await broker.start()
    assert broker._task is None


@pytest.mark.asyncio
async def test_retention_runs_during_continuous_notifications(monkeypatch) -> None:
    broker = SourceEventBroker(
        Settings(
            _env_file=None,
            source_events_listener_database_url=SecretStr(
                "postgresql://user:password@localhost/db"
            ),
        )
    )
    clock = 0.0
    pruned = asyncio.Event()
    broker._now = lambda: clock

    async def dispatch(message_id):
        nonlocal clock
        clock = 3601.0
        if message_id == "first":
            broker._notifications.put_nowait("next")

    async def prune():
        pruned.set()

    monkeypatch.setattr(broker, "_dispatch", dispatch)
    monkeypatch.setattr(broker, "_prune", prune)
    broker._notifications.put_nowait("first")
    task = asyncio.create_task(broker._run())
    try:
        await asyncio.wait_for(pruned.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


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
    sessions = []
    active = 0
    broker = FakeBroker()

    @asynccontextmanager
    async def factory():
        nonlocal active
        active += 1
        try:
            yield sessions.pop(0)
        finally:
            active -= 1

    monkeypatch.setattr(events, "session_scope", factory)
    with TestClient(app) as client:
        assert client.get(route, params={"source_ids": str(SOURCE_A)}).status_code == 503
        app.state.source_event_broker = broker
        assert client.get(route).status_code == 422
        assert client.get(route, params={"source_ids": "invalid"}).status_code == 422
        too_many = ",".join(str(uuid4()) for _ in range(101))
        assert client.get(route, params={"source_ids": too_many}).status_code == 422
        assert client.get(route, params={"source_ids": f"{SOURCE_A},{SOURCE_A}"}).status_code == 422

        sessions.append(Session(workspace_owner=OTHER))
        assert client.get(route, params={"source_ids": str(SOURCE_A)}).status_code == 404
        assert active == 0 and not broker.subscriptions
        sessions.append(Session(rows=[source_row(SOURCE_A)]))
        assert client.get(route, params={"source_ids": f"{SOURCE_A},{SOURCE_B}"}).status_code == 404
        assert active == 0 and not broker.subscriptions

        async def once(request, workspace_id, owner_id, source_ids, initial, subscription, broker):
            assert active == 0
            try:
                yield events._job_event(initial[source_ids[0]])
            finally:
                broker.unsubscribe(subscription)

        monkeypatch.setattr(events, "_stream_events", once)
        sessions.append(Session(rows=[source_row(SOURCE_A)]))
        response = client.get(route, params={"source_ids": str(SOURCE_A)})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        assert json.loads(response.text.split("data: ", 1)[1])["sourceId"] == str(SOURCE_A)
        assert active == 0 and not broker.subscriptions


@pytest.mark.asyncio
async def test_initial_response_uses_job_schema_and_closes_session(monkeypatch) -> None:
    active = 0
    broker = FakeBroker()

    @asynccontextmanager
    async def factory():
        nonlocal active
        active += 1
        try:
            yield Session(rows=[source_row(SOURCE_A)])
        finally:
            active -= 1

    monkeypatch.setattr(events, "session_scope", factory)
    response = await events.source_events(
        WORKSPACE, str(SOURCE_A), Request(broker), AuthUser(id=OWNER)
    )
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
    assert not broker.subscriptions


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
    committed = False
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
            committed = True
            found = await events._load_jobs(
                session,
                owned_workspace.id,
                owner,
                [owned_source.id, foreign_source.id],
            )
            assert set(found) == {owned_source.id}
    finally:
        if committed:
            async with factory() as session:
                for model, identifier in (
                    (Source, owned_source.id),
                    (Source, foreign_source.id),
                    (Workspace, owned_workspace.id),
                    (Workspace, foreign_workspace.id),
                ):
                    item = await session.get(model, identifier)
                    if item is not None:
                        await session.delete(item)
                await session.commit()
        await engine.dispose()

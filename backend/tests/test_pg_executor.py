"""PostgreSQL executor integration tests; opt in with a disposable local database."""

import asyncio
import os
import signal
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.modules.ingestion.infrastructure import pg_executor, source_processor
from app.modules.ingestion.infrastructure.pg_jobs import ProcessingJob
from app.modules.workspaces.infrastructure.models import Source, Workspace


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PG executor integration tests require a loopback PostgreSQL host")
    engine = create_async_engine(url, pool_size=3, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS extensions"))
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
        )
        await connection.execute(text("SET search_path TO public, extensions"))
        await connection.run_sync(SQLModel.metadata.create_all)
        await connection.execute(text("TRUNCATE workspaces CASCADE"))
    monkeypatch.setattr(pg_executor, "session_factory", factory)
    monkeypatch.setattr(source_processor, "session_factory", factory)
    monkeypatch.setattr(source_processor, "engine", engine)
    yield factory
    await engine.dispose()


def test_terminal_error_report_uses_only_safe_diagnostics(monkeypatch) -> None:
    tags = {}
    captured = []
    warnings = []

    class Scope:
        def set_tag(self, key, value):
            tags[key] = value

    @contextmanager
    def scope():
        yield Scope()

    monkeypatch.setattr(pg_executor.sentry_sdk, "push_scope", scope)
    monkeypatch.setattr(pg_executor.logger, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(
        pg_executor.logger,
        "error",
        lambda *args: pytest.fail("ERROR log would duplicate the Sentry event"),
    )
    monkeypatch.setattr(
        pg_executor.sentry_sdk, "capture_exception", lambda error: captured.append(error)
    )
    source_id = uuid4()
    pg_executor._report_terminal_failure(source_id, 4)
    assert tags == {
        "source_id": str(source_id),
        "job_generation": "4",
        "failure_stage": "unknown",
        "failure_code": "recovered_terminal",
        "error_type": "Unknown",
    }
    assert len(captured) == 1
    assert isinstance(captured[0], source_processor.SafeAttemptError)
    assert "provider" not in str(captured[0]).lower()
    assert len(warnings) == 1


async def _source(factory: async_sessionmaker[AsyncSession], *, meeting: bool = False) -> Source:
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="PG executor test")
    source = Source(
        workspace_id=workspace.id,
        owner_id=owner,
        kind="meeting" if meeting else "document",
        title="test.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
        review_state="awaiting_review" if meeting else None,
        status="awaiting_review" if meeting else "queued",
        processing_stage="awaiting_review" if meeting else "uploaded",
    )
    async with factory() as session:
        session.add(workspace)
        await session.flush()
        session.add(source)
        await pg_executor.enqueue_source(session, source)
        await session.commit()
    return source


@pytest.mark.asyncio
async def test_enqueue_is_atomic_and_deduplicated(pg) -> None:
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="Rollback")
    source = Source(
        workspace_id=workspace.id,
        owner_id=owner,
        kind="document",
        title="test.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
    )
    async with pg() as session:
        session.add(workspace)
        await session.flush()
        session.add(source)
        await pg_executor.enqueue_source(session, source)
        await session.rollback()
    async with pg() as session:
        assert await session.get(Source, source.id) is None
        assert await session.get(ProcessingJob, source.id) is None
        session.add(workspace)
        await session.flush()
        session.add(source)
        await pg_executor.enqueue_source(session, source)
        await pg_executor.enqueue_source(session, source)
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(ProcessingJob))
        assert count == 1


@pytest.mark.asyncio
async def test_claim_skip_locked_expiry_and_generation_fence(pg) -> None:
    source = await _source(pg)
    first, second = uuid4(), uuid4()
    claims = await asyncio.gather(
        pg_executor.claim_job(first, 60), pg_executor.claim_job(second, 60)
    )
    assert sum(claim is not None for claim in claims) == 1
    claimed = next(claim for claim in claims if claim is not None)
    first_owner = first if claims[0] else second
    assert claimed == (source.id, 1, 0)
    async with pg() as session:
        await session.execute(
            text("UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second'")
        )
        await session.commit()
    replacement_owner = second if first_owner == first else first
    replacement = await pg_executor.claim_job(replacement_owner, 60)
    assert replacement == (source.id, 2, 0)
    assert not await pg_executor._fenced_update(source.id, first_owner, 1, "status = 'completed'")
    assert await pg_executor._fenced_update(source.id, replacement_owner, 2, "status = 'completed'")


@pytest.mark.asyncio
async def test_review_confirmation_supersedes_running_transcription(pg) -> None:
    source = await _source(pg, meeting=True)
    old_owner = uuid4()
    old_claim = await pg_executor.claim_job(old_owner, 60)
    assert old_claim is not None
    # STT has committed awaiting_review, while the original job has not yet
    # published its completion. The user may confirm in that window.
    async with pg() as session:
        meeting = await session.get(Source, source.id, with_for_update=True)
        meeting.review_state = "confirmed"
        meeting.status = "queued"
        meeting.processing_stage = "confirmed"
        await pg_executor.enqueue_source(session, meeting, supersede_existing=True)
        await session.commit()
    assert not await pg_executor._fenced_update(
        source.id, old_owner, old_claim[1], "status = 'completed'"
    )
    new_claim = await pg_executor.claim_job(uuid4(), 60)
    assert new_claim == (source.id, old_claim[1] + 2, 0)


@pytest.mark.asyncio
async def test_immediate_transcription_retry_supersedes_old_failure(pg) -> None:
    source = await _source(pg, meeting=True)
    old_owner = uuid4()
    old_claim = await pg_executor.claim_job(old_owner, 60)
    assert old_claim is not None
    async with pg() as session:
        meeting = await session.get(Source, source.id)
        meeting.review_state = "transcribing"
        meeting.status = "failed"
        await session.commit()
    async with pg() as session:
        meeting = await session.get(Source, source.id, with_for_update=True)
        meeting.status = "queued"
        meeting.processing_stage = "transcribing"
        await pg_executor.enqueue_source(session, meeting, supersede_existing=True)
        await session.commit()
    assert not await pg_executor._fenced_update(
        source.id, old_owner, old_claim[1], "status = 'failed'"
    )
    replacement = await pg_executor.claim_job(uuid4(), 60)
    assert replacement == (source.id, old_claim[1] + 2, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("next_stage", ["confirmed", "transcribing"])
async def test_review_transition_resets_pending_job_budget(pg, next_stage) -> None:
    source = await _source(pg, meeting=True)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        job.provider_attempts = 3
        meeting = await session.get(Source, source.id, with_for_update=True)
        meeting.review_state = next_stage
        meeting.status = "queued"
        meeting.processing_stage = next_stage
        await pg_executor.enqueue_source(session, meeting, supersede_existing=True)
        await session.commit()
    claim = await pg_executor.claim_job(uuid4(), 60)
    assert claim == (source.id, 2, 0)


@pytest.mark.asyncio
async def test_graceful_cancel_requeues_without_waiting_for_expiry(pg, monkeypatch) -> None:
    source = await _source(pg)
    owner = uuid4()
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    started = asyncio.Event()

    async def slow(_source_id, *, final_attempt):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(pg_executor, "process_source_attempt", slow)
    running = asyncio.create_task(
        pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    )
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        assert job.status == "pending"
        assert job.lease_owner is None
    assert await pg_executor.claim_job(uuid4(), 60) is not None


@pytest.mark.asyncio
async def test_database_failure_requeues_without_spending_provider_attempt(pg, monkeypatch) -> None:
    source = await _source(pg)
    owner = uuid4()
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None

    async def database_failure(_source_id, *, final_attempt):
        raise DBAPIError("database", {}, Exception("temporary"))

    monkeypatch.setattr(pg_executor, "process_source_attempt", database_failure)
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        assert job.status == "pending"
        assert job.provider_attempts == 0
        assert job.next_run_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_terminal_source_failure_survives_crash_before_job_completion(
    pg, monkeypatch
) -> None:
    source = await _source(pg)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        job.provider_attempts = 3
        document = await session.get(Source, source.id)
        document.status = "failed"
        await session.commit()

    async def should_not_run(_source_id, *, final_attempt):
        pytest.fail("terminal failure was already persisted")

    monkeypatch.setattr(pg_executor, "process_source_attempt", should_not_run)
    reports = []
    monkeypatch.setattr(
        pg_executor, "_report_terminal_failure", lambda *args, **_kwargs: reports.append(args)
    )
    owner = uuid4()
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        assert job.status == "failed"
        assert job.provider_attempts == 4
    assert reports == [(source.id, claim[1])]


@pytest.mark.asyncio
async def test_provider_retries_are_bounded_and_review_gate_is_preserved(pg, monkeypatch) -> None:
    source = await _source(pg, meeting=True)
    owner = uuid4()
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    # The reusable pipeline entrypoint sees awaiting_review and does no analysis.
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    async with pg() as session:
        assert (await session.get(ProcessingJob, source.id)).status == "completed"
        meeting = await session.get(Source, source.id)
        assert meeting.status == "awaiting_review"
        meeting.status = "queued"
        meeting.review_state = "confirmed"
        meeting.processing_stage = "confirmed"
        await pg_executor.enqueue_source(session, meeting)
        await session.commit()

    async def fail(_source_id, *, final_attempt):
        assert final_attempt is False
        return RuntimeError("provider unavailable")

    monkeypatch.setattr(pg_executor, "process_source_attempt", fail)
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        assert job.status == "pending"
        assert job.provider_attempts == 1
        assert job.next_run_at > datetime.now(UTC)
        job.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        job.provider_attempts = 3
        await session.commit()

    async def final_fail(_source_id, *, final_attempt):
        assert final_attempt is True
        return RuntimeError("provider unavailable")

    monkeypatch.setattr(pg_executor, "process_source_attempt", final_fail)
    reports = []
    monkeypatch.setattr(pg_executor, "_report_terminal_failure", lambda *args: reports.append(args))
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        assert job.status == "failed"
        assert job.provider_attempts == 4
    assert len(reports) == 1
    assert reports[0][:2] == (source.id, claim[1])
    assert isinstance(reports[0][2], source_processor.SafeAttemptError)


@pytest.mark.asyncio
async def test_stale_terminal_failure_is_not_reported(pg, monkeypatch) -> None:
    source = await _source(pg)
    async with pg() as session:
        job = await session.get(ProcessingJob, source.id)
        job.provider_attempts = 3
        await session.commit()
    owner = uuid4()
    claim = await pg_executor.claim_job(owner, 60)
    assert claim is not None
    async with pg() as session:
        await session.execute(
            text("UPDATE processing_jobs SET lease_expires_at = now() - interval '1 second'")
        )
        await session.commit()
    assert await pg_executor.claim_job(uuid4(), 60) is not None

    async def fail(_source_id, *, final_attempt):
        return RuntimeError("provider failed")

    reports = []
    monkeypatch.setattr(pg_executor, "process_source_attempt", fail)
    monkeypatch.setattr(pg_executor, "_report_terminal_failure", lambda *args: reports.append(args))
    await pg_executor._execute_claim(source.id, owner, claim[1], claim[2], 60)
    assert reports == []


@pytest.mark.asyncio
async def test_executor_start_wake_stop_and_recovery(pg, monkeypatch) -> None:
    source = await _source(pg)
    started = asyncio.Event()

    async def slow(_source_id, *, final_attempt):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(pg_executor, "process_source_attempt", slow)
    settings = Settings(
        _env_file=None,
        processing_executor="postgres",
        pg_executor_poll_seconds=0.2,
        pg_executor_lease_seconds=60,
    )
    first = pg_executor.PostgresExecutor(settings)
    first.start()
    try:
        pg_executor.wake_executors()
        await asyncio.wait_for(started.wait(), timeout=3)
    finally:
        await first.stop()
    async with pg() as session:
        assert (await session.get(ProcessingJob, source.id)).status == "pending"

    async def finish(_source_id, *, final_attempt):
        return None

    monkeypatch.setattr(pg_executor, "process_source_attempt", finish)
    second = pg_executor.PostgresExecutor(settings)
    second.start()
    try:
        pg_executor.wake_executors()

        async def completed() -> None:
            while True:
                async with pg() as session:
                    if (await session.get(ProcessingJob, source.id)).status == "completed":
                        return
                await asyncio.sleep(0.02)

        await asyncio.wait_for(completed(), timeout=3)
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_executor_startup_commits_missing_job_before_first_claim(pg, monkeypatch) -> None:
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="Startup recovery")
    source = Source(
        workspace_id=workspace.id,
        owner_id=owner,
        kind="document",
        title="test.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
        status="queued",
        processing_stage="uploaded",
    )
    async with pg() as session:
        session.add(workspace)
        await session.flush()
        session.add(source)
        await session.commit()

    saw_claim = asyncio.Event()

    async def inspect_claim(_owner, _lease_seconds):
        async with pg() as session:
            assert (await session.get(ProcessingJob, source.id)).status == "pending"
        saw_claim.set()
        return None

    monkeypatch.setattr(pg_executor, "claim_job", inspect_claim)
    monkeypatch.setattr(
        pg_executor,
        "process_source_attempt",
        lambda *_args, **_kwargs: pytest.fail("Recovery must not call providers"),
    )
    settings = Settings(
        _env_file=None, processing_executor="postgres", pg_executor_poll_seconds=0.2
    )
    executor = pg_executor.PostgresExecutor(settings)
    executor.start()
    try:
        await asyncio.wait_for(saw_claim.wait(), timeout=3)
        assert executor._reconciled
    finally:
        await executor.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_step", ["recovery", "commit"])
async def test_executor_retries_recovery_after_database_failure_before_claim(
    monkeypatch, failure_step
) -> None:
    attempts = 0
    commits = 0
    commit_attempts = 0
    claimed = asyncio.Event()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def commit(self):
            nonlocal commits, commit_attempts
            commit_attempts += 1
            if failure_step == "commit" and commit_attempts == 1:
                raise DBAPIError("recovery commit", {}, RuntimeError("synthetic database outage"))
            commits += 1

    async def recover(_session):
        nonlocal attempts
        attempts += 1
        if failure_step == "recovery" and attempts == 1:
            raise DBAPIError("recovery", {}, RuntimeError("synthetic database outage"))
        return 1

    async def claim(_owner, _lease_seconds):
        assert attempts == 2
        assert commits == 1
        claimed.set()
        return None

    monkeypatch.setattr(pg_executor, "session_factory", Session)
    monkeypatch.setattr(pg_executor, "recover_missing_jobs", recover)
    monkeypatch.setattr(pg_executor, "claim_job", claim)
    monkeypatch.setattr(
        pg_executor,
        "process_source_attempt",
        lambda *_args, **_kwargs: pytest.fail("Recovery must not call providers"),
    )
    settings = Settings(
        _env_file=None, processing_executor="postgres", pg_executor_poll_seconds=0.2
    )
    executor = pg_executor.PostgresExecutor(settings)
    executor.start()
    try:
        await asyncio.wait_for(claimed.wait(), timeout=3)
        assert executor._reconciled
        assert attempts == 2
    finally:
        await executor.stop()


@pytest.mark.asyncio
async def test_app_lifespan_selects_postgres_executor(monkeypatch) -> None:
    from app import main

    calls = []

    class FakeExecutor:
        def __init__(self, settings):
            calls.append("created")

        def start(self):
            calls.append("started")

        async def stop(self):
            calls.append("stopped")

    monkeypatch.setattr(main, "PostgresExecutor", FakeExecutor)
    app = main.create_app(Settings(_env_file=None, processing_executor="postgres"))
    async with app.router.lifespan_context(app):
        assert calls == ["created", "started"]
    assert calls == ["created", "started", "stopped"]


@pytest.mark.asyncio
async def test_app_lifespan_can_enqueue_without_embedded_executor(monkeypatch) -> None:
    from app import main

    def unexpected_executor(settings):
        pytest.fail("API must not start a worker when PG_EXECUTOR_ENABLED=false")

    monkeypatch.setattr(main, "PostgresExecutor", unexpected_executor)
    settings = Settings(_env_file=None, processing_executor="postgres", pg_executor_enabled=False)
    app = main.create_app(settings)
    async with app.router.lifespan_context(app):
        assert app.state.settings.processing_executor == "postgres"


@pytest.mark.asyncio
async def test_standalone_worker_ignores_api_embedded_flag_and_stops(monkeypatch) -> None:
    from app.modules.ingestion.infrastructure import pg_worker

    events = []

    class FakeExecutor:
        def __init__(self, settings):
            assert settings.pg_executor_enabled is False

        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(pg_worker, "PostgresExecutor", FakeExecutor)
    monkeypatch.setattr(
        pg_worker, "configure_observability", lambda settings: events.append("configured")
    )
    stop = asyncio.Event()
    settings = Settings(_env_file=None, processing_executor="postgres", pg_executor_enabled=False)
    running = asyncio.create_task(pg_worker.run_worker(settings, stop_event=stop))
    await asyncio.sleep(0)
    assert events == ["configured", "started"]
    stop.set()
    await asyncio.wait_for(running, timeout=1)
    assert events == ["configured", "started", "stopped"]


@pytest.mark.asyncio
async def test_standalone_worker_rejects_celery_setting() -> None:
    from app.modules.ingestion.infrastructure.pg_worker import run_worker

    with pytest.raises(ValueError, match="PROCESSING_EXECUTOR=postgres"):
        await run_worker(Settings(_env_file=None, processing_executor="celery"))


@pytest.mark.asyncio
async def test_standalone_worker_stops_on_sigterm(monkeypatch) -> None:
    from app.modules.ingestion.infrastructure import pg_worker

    handlers = {}
    events = []
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda signum, callback: handlers.setdefault(signum, callback)
    )
    monkeypatch.setattr(loop, "remove_signal_handler", lambda signum: handlers.pop(signum))
    monkeypatch.setattr(pg_worker, "configure_observability", lambda settings: None)

    class FakeExecutor:
        def __init__(self, settings):
            pass

        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(pg_worker, "PostgresExecutor", FakeExecutor)
    settings = Settings(_env_file=None, processing_executor="postgres", pg_executor_enabled=False)
    running = asyncio.create_task(pg_worker.run_worker(settings))
    await asyncio.sleep(0)
    assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
    handlers[signal.SIGTERM]()
    await asyncio.wait_for(running, timeout=1)
    assert events == ["started", "stopped"]
    assert handlers == {}


@pytest.mark.asyncio
async def test_upload_selects_atomic_postgres_enqueue(monkeypatch) -> None:
    from importlib import import_module

    workspace_router = import_module("app.api.workspaces.router")

    events = []
    source = object()

    class Session:
        async def commit(self):
            events.append("commit")

    async def enqueue(session, actual_source):
        assert actual_source is source
        events.append("enqueue")

    monkeypatch.setattr(
        workspace_router,
        "get_settings",
        lambda: Settings(_env_file=None, processing_executor="postgres", pg_executor_enabled=False),
    )
    monkeypatch.setattr(workspace_router, "enqueue_pg_source", enqueue)
    monkeypatch.setattr(workspace_router, "wake_executors", lambda: events.append("wake"))
    await workspace_router._persist_and_enqueue_source(source, Session())
    assert events == ["enqueue", "commit", "wake"]


@pytest.mark.asyncio
async def test_api_enqueue_only_mode_returns_with_durable_pending_job(pg, monkeypatch) -> None:
    from importlib import import_module

    from app import main

    workspace_router = import_module("app.api.workspaces.router")
    settings = Settings(_env_file=None, processing_executor="postgres", pg_executor_enabled=False)
    monkeypatch.setattr(workspace_router, "get_settings", lambda: settings)
    monkeypatch.setattr(
        main,
        "PostgresExecutor",
        lambda settings: pytest.fail("API must not start processing"),
    )
    monkeypatch.setattr(
        pg_executor,
        "process_source_attempt",
        lambda *args, **kwargs: pytest.fail("Request must not await source processing"),
    )
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="Enqueue only")
    source = Source(
        workspace_id=workspace.id,
        owner_id=owner,
        kind="document",
        title="test.txt",
        object_path=str(uuid4()),
        content_type="text/plain",
        size_bytes=1,
    )
    app = main.create_app(settings)
    async with app.router.lifespan_context(app), pg() as session:
        session.add(workspace)
        await session.flush()
        session.add(source)
        await workspace_router._persist_and_enqueue_source(source, session)
    async with pg() as session:
        assert (await session.get(Source, source.id)).status == "queued"
        assert (await session.get(ProcessingJob, source.id)).status == "pending"


def test_executor_selection_defaults_to_celery() -> None:
    defaults = Settings(_env_file=None)
    assert defaults.processing_executor == "celery"
    assert defaults.pg_executor_enabled is True
    assert (
        Settings(_env_file=None, processing_executor="postgres").processing_executor == "postgres"
    )


@pytest.mark.asyncio
async def test_job_migration_enables_rls_without_browser_policy(pg) -> None:
    from importlib import import_module

    revision = import_module("migrations.versions.202609240001_processing_jobs")
    engine = pg.kw["bind"]

    def migrate(connection, upgrade):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            (revision.upgrade if upgrade else revision.downgrade)()

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE processing_jobs"))
        await connection.run_sync(migrate, True)
        result = await connection.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid = 'processing_jobs'::regclass")
        )
        assert result.scalar_one() is True
        policies = await connection.execute(
            text("SELECT count(*) FROM pg_policies WHERE tablename = 'processing_jobs'")
        )
        assert policies.scalar_one() == 0
        await connection.run_sync(migrate, False)
        missing = await connection.execute(text("SELECT to_regclass('processing_jobs')"))
        assert missing.scalar_one() is None
        await connection.run_sync(migrate, True)

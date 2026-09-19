"""Small, restart-safe PostgreSQL executor for one API process.

The job table is a schedule, not the source of processing checkpoints. Claim and
completion use a generation fence; source execution retains its advisory locks.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid4
from weakref import WeakSet

import sentry_sdk
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.core.database import session_factory
from app.modules.ingestion.infrastructure.pg_jobs import ProcessingJob
from app.modules.ingestion.infrastructure.source_processor import process_source_attempt
from app.modules.workspaces.domain.source_state import SourceStatus
from app.modules.workspaces.infrastructure.models import Source

logger = logging.getLogger(__name__)
_executors: WeakSet["PostgresExecutor"] = WeakSet()


def wake_executors() -> None:
    """Wake locally after commit; other API processes discover work on their next poll."""
    for executor in list(_executors):
        executor.wake()


def _report_terminal_failure(source_id: UUID, generation: int) -> None:
    # Provider errors can contain user content. Report a generic exception and
    # only stable job identifiers to logs and telemetry.
    # Logging integration records ERROR as a Sentry event; WARN plus the scoped
    # exception below produces one terminal event instead of two.
    logger.warning(
        "PostgreSQL ingestion provider retries exhausted (source_id=%s, generation=%s)",
        source_id,
        generation,
    )
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("source_id", str(source_id))
        scope.set_tag("job_generation", str(generation))
        sentry_sdk.capture_exception(RuntimeError("Ingestion provider retries exhausted"))


async def enqueue_source(
    session: AsyncSession, source: Source, *, supersede_existing: bool = False
) -> None:
    """Flush with the caller's source transaction; caller commits both or neither."""
    await session.flush()
    statement = insert(ProcessingJob).values(
        source_id=source.id,
        status="pending",
        stage=str(source.processing_stage),
        provider_attempts=0,
        claim_generation=0,
        next_run_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[ProcessingJob.source_id],
        set_={
            "status": "pending",
            "stage": str(source.processing_stage),
            "provider_attempts": 0,
            "claim_generation": ProcessingJob.claim_generation + 1,
            "lease_owner": None,
            "lease_expires_at": None,
            "next_run_at": datetime.now(UTC),
            "last_error": None,
            "updated_at": datetime.now(UTC),
        },
        where=(
            ProcessingJob.status.in_(["completed", "failed", "cancelled"])
            | (ProcessingJob.status.in_(["pending", "running"]) if supersede_existing else False)
        ),
    )
    await session.exec(statement)


async def claim_job(owner: UUID, lease_seconds: int) -> tuple[UUID, int, int] | None:
    # One short transaction; no lock is held while a provider runs. SKIP LOCKED
    # permits other API processes to claim another source without contention.
    async with session_factory() as session:
        result = await session.execute(
            text("""
                WITH candidate AS (
                    SELECT source_id FROM processing_jobs
                    WHERE (status = 'pending' AND next_run_at <= now())
                       OR (status = 'running' AND lease_expires_at <= now())
                    ORDER BY next_run_at, source_id
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE processing_jobs AS job
                SET status = 'running', lease_owner = :owner,
                    lease_expires_at = now() + (:lease_seconds * interval '1 second'),
                    claim_generation = job.claim_generation + 1, updated_at = now()
                FROM candidate WHERE job.source_id = candidate.source_id
                RETURNING job.source_id, job.claim_generation, job.provider_attempts
            """),
            {"owner": owner, "lease_seconds": lease_seconds},
        )
        row = result.first()
        await session.commit()
        return (row[0], row[1], row[2]) if row else None


async def _fenced_update(
    source_id: UUID, owner: UUID, generation: int, assignment: str, parameters: dict | None = None
) -> bool:
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                UPDATE processing_jobs SET {assignment}, updated_at = now()
                WHERE source_id = :source_id AND status = 'running'
                  AND lease_owner = :owner AND claim_generation = :generation
                  AND lease_expires_at > now()
            """),
            {
                "source_id": source_id,
                "owner": owner,
                "generation": generation,
                **(parameters or {}),
            },
        )
        await session.commit()
        return result.rowcount == 1


async def _renew(source_id: UUID, owner: UUID, generation: int, seconds: int) -> bool:
    return await _fenced_update(
        source_id,
        owner,
        generation,
        "lease_expires_at = now() + (:seconds * interval '1 second')",
        {"seconds": seconds},
    )


async def _heartbeat(source_id: UUID, owner: UUID, generation: int, seconds: int) -> None:
    while True:
        await asyncio.sleep(max(10, seconds // 3))
        try:
            if not await _renew(source_id, owner, generation, seconds):
                return
        except DBAPIError:
            # A later renewal may succeed. A prolonged outage expires the lease;
            # the source advisory lock still serializes a replacement attempt.
            logger.exception("PostgreSQL job lease renewal failed")


async def _execute_claim(
    source_id: UUID, owner: UUID, generation: int, attempts: int, lease_seconds: int
) -> None:
    heartbeat = asyncio.create_task(_heartbeat(source_id, owner, generation, lease_seconds))
    try:
        if attempts >= 3:
            # A crash between the terminal source update and job completion must
            # not spend a fifth provider attempt on recovery.
            async with session_factory() as session:
                source = await session.get(Source, source_id)
            if source is not None and source.status == SourceStatus.FAILED:
                updated = await _fenced_update(
                    source_id,
                    owner,
                    generation,
                    "status = 'failed', lease_owner = NULL, lease_expires_at = NULL, "
                    "provider_attempts = provider_attempts + 1",
                )
                if updated:
                    _report_terminal_failure(source_id, generation)
                return
        try:
            error = await process_source_attempt(source_id, final_attempt=attempts >= 3)
        except DBAPIError:
            # Infrastructure failures do not consume the bounded provider budget.
            await _fenced_update(
                source_id,
                owner,
                generation,
                "status = 'pending', lease_owner = NULL, lease_expires_at = NULL, "
                "next_run_at = now() + interval '30 seconds'",
            )
            return
        if error is None:
            await _fenced_update(
                source_id,
                owner,
                generation,
                "status = 'completed', lease_owner = NULL, lease_expires_at = NULL, "
                "last_error = NULL",
            )
        elif attempts >= 3:
            updated = await _fenced_update(
                source_id,
                owner,
                generation,
                "status = 'failed', lease_owner = NULL, lease_expires_at = NULL, "
                "provider_attempts = provider_attempts + 1, last_error = :error",
                {"error": str(error)[:2000]},
            )
            if updated:
                _report_terminal_failure(source_id, generation)
        else:
            # 10, 20, 40 seconds; the fourth failure is terminal.
            await _fenced_update(
                source_id,
                owner,
                generation,
                "status = 'pending', lease_owner = NULL, lease_expires_at = NULL, "
                "provider_attempts = provider_attempts + 1, "
                "next_run_at = now() + (:delay * interval '1 second'), last_error = :error",
                {"delay": min(300, 10 * 2**attempts), "error": str(error)[:2000]},
            )
    except asyncio.CancelledError:
        # Graceful API shutdown releases this claim immediately. A hard kill is
        # recovered by lease expiry instead.
        with suppress(DBAPIError):
            await asyncio.shield(
                _fenced_update(
                    source_id,
                    owner,
                    generation,
                    "status = 'pending', lease_owner = NULL, lease_expires_at = NULL, "
                    "next_run_at = now()",
                )
            )
        raise
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


class PostgresExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.owner = uuid4()
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        logger.info(
            "Starting PostgreSQL ingestion executor (lease=%ss, initial_poll=%ss)",
            self.settings.pg_executor_lease_seconds,
            self.settings.pg_executor_poll_seconds,
        )
        _executors.add(self)
        self._task = asyncio.create_task(self._run(), name="postgres-ingestion-executor")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self._stopping.set()
        _executors.discard(self)
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        idle_seconds = self.settings.pg_executor_poll_seconds
        while not self._stopping.is_set():
            self._wake.clear()
            try:
                claim = await claim_job(self.owner, self.settings.pg_executor_lease_seconds)
                if claim is not None:
                    idle_seconds = self.settings.pg_executor_poll_seconds
                    await _execute_claim(
                        claim[0],
                        self.owner,
                        claim[1],
                        claim[2],
                        self.settings.pg_executor_lease_seconds,
                    )
                    continue
            except DBAPIError:
                logger.exception("PostgreSQL executor database failure; retrying")
            except Exception:
                logger.exception("PostgreSQL executor failure; retrying")
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=idle_seconds)
            idle_seconds = min(60.0, idle_seconds * 2)

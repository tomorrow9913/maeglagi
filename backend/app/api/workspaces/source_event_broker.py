"""One direct PostgreSQL listener per API process, with local SSE fanout.

PGMQ is an append-only event log here: claiming messages with pgmq.read would
steal them from other API processes and their connected clients.
"""

import asyncio
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

from app.core.config import Settings
from app.core.database import normalize_database_url

logger = logging.getLogger(__name__)

CHANNEL = "maeglagi_source_events"
QUEUE_SIZE = 64
NOTIFICATION_QUEUE_SIZE = 2048
RETENTION_SECONDS = 86400
LIVENESS_SECONDS = 30


@dataclass(frozen=True)
class SourceEventKey:
    owner_id: UUID
    workspace_id: UUID
    source_id: UUID


@dataclass(eq=False)
class SourceSubscription:
    owner_id: UUID
    workspace_id: UUID
    source_ids: frozenset[UUID]
    queue: asyncio.Queue[SourceEventKey | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE)
    )

    def accepts(self, event: SourceEventKey) -> bool:
        return (
            self.owner_id == event.owner_id
            and self.workspace_id == event.workspace_id
            and event.source_id in self.source_ids
        )

    def reset(self) -> None:
        # The stream ends and its client reconnects for an authoritative snapshot.
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(None)


class SourceEventBroker:
    def __init__(self, settings: Settings) -> None:
        raw_url = settings.source_events_listener_database_url.get_secret_value()
        if not raw_url:
            raw_url = settings.database_url
        url = normalize_database_url(raw_url)
        if not url.startswith("postgresql+asyncpg://"):
            raise RuntimeError("SOURCE_EVENTS_LISTENER_DATABASE_URL must be a PostgreSQL URL")
        if urlsplit(url).port == 6543:
            raise RuntimeError("SOURCE_EVENTS_LISTENER_DATABASE_URL cannot use port 6543")
        self._dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._connection: asyncpg.Connection | None = None
        self._notifications: asyncio.Queue[str | None] = asyncio.Queue(
            maxsize=NOTIFICATION_QUEUE_SIZE
        )
        self._subscribers: set[SourceSubscription] = set()
        self._task: asyncio.Task[None] | None = None
        self._now = time.monotonic
        self.healthy = False

    async def start(self) -> None:
        try:
            await self._connect()
            await self._prune()
        except Exception:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
            self.healthy = False
            raise RuntimeError(
                "Source events require pgmq migration and a direct/session PostgreSQL listener URL"
            ) from None
        self._task = asyncio.create_task(self._run(), name="source-event-listener")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.healthy = False
        self._reset_subscribers()
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    def subscribe(
        self, owner_id: UUID, workspace_id: UUID, source_ids: list[UUID]
    ) -> SourceSubscription:
        if not self.healthy:
            raise RuntimeError("Source event listener unavailable")
        subscription = SourceSubscription(owner_id, workspace_id, frozenset(source_ids))
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: SourceSubscription) -> None:
        self._subscribers.discard(subscription)

    def _notify(
        self, _connection: asyncpg.Connection, _pid: int, _channel: str, value: str
    ) -> None:
        try:
            self._notifications.put_nowait(value)
        except asyncio.QueueFull:
            self._reset_subscribers()
            self._drain_notifications()

    def _terminated(self, _connection: asyncpg.Connection) -> None:
        self._drain_notifications()
        self._notifications.put_nowait(None)

    def _drain_notifications(self) -> None:
        while not self._notifications.empty():
            self._notifications.get_nowait()

    def _reset_subscribers(self) -> None:
        for subscriber in tuple(self._subscribers):
            subscriber.reset()

    async def _connect(self) -> None:
        connection = await asyncpg.connect(self._dsn, timeout=10, command_timeout=10)
        try:
            ready = await connection.fetchval(
                "SELECT to_regclass('pgmq.q_source_events') IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'sources_pgmq_events_insert') "
                "AND EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'sources_pgmq_events_update')"
            )
            if not ready:
                raise RuntimeError("Source event pgmq queue or triggers are missing")
            await connection.add_listener(CHANNEL, self._notify)
            connection.add_termination_listener(self._terminated)
        except BaseException:
            connection.terminate()
            raise
        self._connection = connection
        self.healthy = True

    async def _run(self) -> None:
        retry = 1
        next_prune = self._now() + 3600
        while True:
            try:
                message_id = await asyncio.wait_for(
                    self._notifications.get(),
                    timeout=max(0, min(LIVENESS_SECONDS, next_prune - self._now())),
                )
                if message_id is None:
                    raise ConnectionError("Source event listener disconnected")
                await self._dispatch(message_id)
                retry = 1
            except TimeoutError:
                try:
                    assert self._connection is not None
                    await self._connection.fetchval("SELECT 1")
                except Exception:
                    self._terminated(self._connection)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Source event listener interrupted; clients will resync")
                self.healthy = False
                self._reset_subscribers()
                self._drain_notifications()
                if self._connection is not None:
                    await self._connection.close()
                    self._connection = None
                self._drain_notifications()
                while not self.healthy:
                    try:
                        await asyncio.sleep(retry)
                        await self._connect()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Source event listener reconnect failed")
                        retry = min(retry * 2, 30)
                # Snapshot on reconnect covers all events missed while disconnected.
                self._reset_subscribers()
            if self._now() >= next_prune:
                try:
                    await self._prune()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Source event queue retention failed")
                next_prune = self._now() + 3600

    async def _dispatch(self, message_id: str) -> None:
        try:
            parsed_id = int(message_id)
        except ValueError:
            logger.warning("Ignoring malformed source event notification")
            return
        assert self._connection is not None
        value = await self._connection.fetchval(
            "SELECT message FROM pgmq.q_source_events WHERE msg_id = $1", parsed_id
        )
        if value is None:
            self._reset_subscribers()
            return
        message = json.loads(value) if isinstance(value, str) else value
        event = SourceEventKey(
            owner_id=UUID(message["owner_id"]),
            workspace_id=UUID(message["workspace_id"]),
            source_id=UUID(message["source_id"]),
        )
        for subscriber in tuple(self._subscribers):
            if not subscriber.accepts(event):
                continue
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscriber.reset()

    async def _prune(self) -> None:
        # A reconnecting stream reads Source afresh, so old queue rows are not needed.
        assert self._connection is not None
        await self._connection.execute(
            "DELETE FROM pgmq.q_source_events WHERE enqueued_at < "
            "now() - ($1::integer * interval '1 second')",
            RETENTION_SECONDS,
        )

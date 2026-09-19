"""Hold source and workspace PostgreSQL advisory locks across checkpoint commits."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

# A waiting advisory lock must never occupy a connection from the application
# pool while the writer needs that pool to commit its checkpoints. Serialize
# waits locally and use a separate transaction-pool-compatible connection.
_lock_gate = asyncio.Semaphore(1)


def _key(identifier: UUID) -> int:
    return int.from_bytes(identifier.bytes[:8], "big") & ((1 << 63) - 1)


@asynccontextmanager
async def analysis_lock(
    engine: AsyncEngine, source_id: UUID, workspace_id: UUID
) -> AsyncIterator[None]:
    # Match the server processor's xact lock namespace and order. A distinct
    # NullPool engine avoids starving the main pool even when its size is one.
    async with _lock_gate:
        lock_engine = create_async_engine(
            engine.url, poolclass=NullPool, pool_pre_ping=True, hide_parameters=True
        )
        try:
            async with lock_engine.connect() as connection:
                await connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
                await connection.execute(text("SET LOCAL statement_timeout = 0"))
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": _key(source_id)}
                )
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _key(workspace_id) - (1 << 63)},
                )
                try:
                    yield
                finally:
                    await connection.rollback()
        finally:
            await lock_engine.dispose()

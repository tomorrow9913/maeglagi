"""Hold source and workspace PostgreSQL advisory locks across checkpoint commits."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


@dataclass
class _WorkspaceGate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass
class _LocalGates:
    capacity: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    workspaces: dict[UUID, _WorkspaceGate] = field(default_factory=dict)
    users: int = 0


_local_gates: dict[asyncio.AbstractEventLoop, _LocalGates] = {}


@asynccontextmanager
async def _analysis_slot(workspace_id: UUID) -> AsyncIterator[None]:
    """Conflicting waiters use no DB connections or unrelated-work capacity."""
    loop = asyncio.get_running_loop()
    gates = _local_gates.setdefault(loop, _LocalGates())
    gates.users += 1
    workspace_gate = gates.workspaces.setdefault(workspace_id, _WorkspaceGate())
    workspace_gate.users += 1
    try:
        async with workspace_gate.lock, gates.capacity:
            yield
    finally:
        workspace_gate.users -= 1
        if not workspace_gate.users:
            gates.workspaces.pop(workspace_id, None)
        gates.users -= 1
        if not gates.users:
            # Also release event-loop references after cancellation or shutdown.
            _local_gates.pop(loop, None)


def _key(identifier: UUID) -> int:
    return int.from_bytes(identifier.bytes[:8], "big") & ((1 << 63) - 1)


@asynccontextmanager
async def analysis_lock(
    engine: AsyncEngine, source_id: UUID, workspace_id: UUID
) -> AsyncIterator[None]:
    # Match the server processor's xact lock namespace and order. A distinct
    # NullPool engine avoids starving the main pool even when its size is one.
    async with _analysis_slot(workspace_id):
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

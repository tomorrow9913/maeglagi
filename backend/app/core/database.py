import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings


def normalize_database_url(url: str) -> str:
    # Guard against copying a complete Supabase URI after the SQLAlchemy scheme.
    duplicated_prefix = "postgresql+asyncpg://postgresql://"
    if url.startswith(duplicated_prefix):
        url = "postgresql+asyncpg://" + url.removeprefix(duplicated_prefix)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _database_url() -> str:
    return normalize_database_url(get_settings().database_url)


_pool_limits = (
    {"pool_size": 4, "max_overflow": 1} if get_settings().processing_executor == "postgres" else {}
)
engine: AsyncEngine = create_async_engine(
    _database_url(), pool_pre_ping=True, hide_parameters=True, **_pool_limits
)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _close_session(session: AsyncSession) -> None:
    """Return a checked-out connection even when its request is cancelled."""
    cleanup = asyncio.create_task(session.close())
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # Shield keeps close alive. Repeated cancellation (for example a
            # disconnect followed by server shutdown) still must not orphan it.
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = session_factory()
    try:
        yield session
    finally:
        await _close_session(session)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session

from collections.abc import AsyncIterator

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


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session

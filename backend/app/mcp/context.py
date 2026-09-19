"""Request-scoped MCP identity and application dependencies."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import Context
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import AuthUser
from app.core.database import session_factory


def current_user(ctx: Context) -> AuthUser:
    """Read only the identity verified at the HTTP transport boundary."""
    user = getattr(ctx.request_context.request.state, "mcp_user", None)
    if not isinstance(user, AuthUser):
        raise PermissionError("MCP authentication required")
    return user


@asynccontextmanager
async def mcp_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session

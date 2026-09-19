"""Workspace MCP tools backed by the shared agent workflow service."""

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from app.core.config import Settings
from app.mcp.context import current_user
from app.mcp.errors import workflow_call

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
CREATE = ToolAnnotations(destructiveHint=False, idempotentHint=False, openWorldHint=False)


def register(server: MCPServer, settings: Settings) -> None:
    @server.tool(annotations=READ)
    async def list_workspaces(ctx: Context) -> list[dict[str, Any]]:
        """List only the authenticated account's workspaces."""
        owner_id = current_user(ctx).id
        return await workflow_call(settings, lambda svc: svc.list_workspaces(owner_id=owner_id))

    @server.tool(annotations=CREATE)
    async def create_workspace(
        name: Annotated[str, Field(min_length=1, max_length=120)], ctx: Context
    ) -> dict[str, Any]:
        """Create a keyless workspace for work performed by this external agent."""
        owner_id = current_user(ctx).id
        return await workflow_call(
            settings, lambda svc: svc.create_workspace(owner_id=owner_id, name=name)
        )

"""Workspace directory read tools."""

from typing import Annotated, Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from app.core.config import Settings
from app.mcp.context import current_user
from app.mcp.errors import knowledge_call

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
PageSize = Annotated[int, Field(ge=1, le=50)]
PageOffset = Annotated[int, Field(ge=0, le=10_000)]


def register(server: MCPServer, settings: Settings) -> None:
    @server.tool(annotations=READ)
    async def list_people(
        workspace_id: UUID, ctx: Context, limit: PageSize = 20, offset: PageOffset = 0
    ) -> list[dict[str, Any]]:
        """List account-owned workspace people and aliases with bounded pagination."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.list_people(
                owner_id=owner_id, workspace_id=workspace_id, limit=limit, offset=offset
            ),
        )

    @server.tool(annotations=READ)
    async def list_projects(
        workspace_id: UUID, ctx: Context, limit: PageSize = 20, offset: PageOffset = 0
    ) -> list[dict[str, Any]]:
        """List account-owned workspace projects with bounded pagination."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.list_projects(
                owner_id=owner_id, workspace_id=workspace_id, limit=limit, offset=offset
            ),
        )

    @server.tool(annotations=READ)
    async def project_participants(
        workspace_id: UUID,
        project_id: UUID,
        ctx: Context,
        limit: PageSize = 20,
        offset: PageOffset = 0,
    ) -> list[dict[str, Any]]:
        """List a project's participants after account and workspace checks."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.project_participants(
                owner_id=owner_id,
                workspace_id=workspace_id,
                project_id=project_id,
                limit=limit,
                offset=offset,
            ),
        )

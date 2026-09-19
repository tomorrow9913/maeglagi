"""Grounded knowledge reads, without any server-side AI calls."""

from datetime import datetime
from typing import Annotated, Any, Literal
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
    async def lexical_search(
        workspace_id: UUID,
        query: Annotated[str, Field(min_length=1, max_length=500)],
        ctx: Context,
        limit: Annotated[int, Field(ge=1, le=8)] = 8,
    ) -> list[dict[str, Any]]:
        """Find only approved, owner-scoped passages for an answer by your own agent."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.lexical_search(
                owner_id=owner_id, workspace_id=workspace_id, query=query, limit=limit
            ),
        )

    @server.tool(annotations=READ)
    async def timeline(
        workspace_id: UUID,
        ctx: Context,
        limit: PageSize = 20,
        offset: PageOffset = 0,
        kind: Literal["event", "decision", "task", "issue", "fact", "summary"] | None = None,
    ) -> list[dict[str, Any]]:
        """Read a bounded page of grounded context records and their source references."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.timeline(
                owner_id=owner_id,
                workspace_id=workspace_id,
                limit=limit,
                offset=offset,
                kind=kind,
            ),
        )

    @server.tool(annotations=READ)
    async def get_context_store(workspace_id: UUID, ctx: Context) -> dict[str, Any]:
        """Read the current grounded workspace state and cited decisions/actions."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.context_store(owner_id=owner_id, workspace_id=workspace_id),
        )

    @server.tool(annotations=READ)
    async def graph_nodes(
        workspace_id: UUID, ctx: Context, limit: PageSize = 20, offset: PageOffset = 0
    ) -> dict[str, Any]:
        """Read a bounded page of owned knowledge graph entities."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.graph_nodes(
                owner_id=owner_id, workspace_id=workspace_id, limit=limit, offset=offset
            ),
        )

    @server.tool(annotations=READ)
    async def graph_relations(
        workspace_id: UUID,
        ctx: Context,
        at: datetime | None = None,
        limit: PageSize = 20,
        offset: PageOffset = 0,
    ) -> dict[str, Any]:
        """Read relations valid at a chosen time from a bounded graph page."""
        owner_id = current_user(ctx).id
        return await knowledge_call(
            ctx,
            lambda svc: svc.graph_relations(
                owner_id=owner_id,
                workspace_id=workspace_id,
                at=at,
                limit=limit,
                offset=offset,
            ),
        )

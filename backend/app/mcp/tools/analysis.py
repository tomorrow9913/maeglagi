"""External agent analysis exchange; Maeglagi does not run a model."""

from typing import Annotated, Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from app.core.config import Settings
from app.mcp.context import current_user
from app.mcp.errors import workflow_call

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
SUBMIT = ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False)


def register(server: MCPServer, settings: Settings) -> None:
    @server.tool(annotations=READ)
    async def analysis_context(workspace_id: UUID, source_id: UUID, ctx: Context) -> dict[str, Any]:
        """Get the confirmed source, schema, revision and fingerprint for external analysis."""
        owner_id = current_user(ctx).id
        return await workflow_call(
            settings,
            lambda svc: svc.analysis_context(
                owner_id=owner_id, workspace_id=workspace_id, source_id=source_id
            ),
        )

    @server.tool(annotations=SUBMIT)
    async def submit_analysis(
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: Annotated[int, Field(ge=0)],
        expected_fingerprint: Annotated[str, Field(min_length=32, max_length=128)],
        result: dict[str, Any],
        ctx: Context,
    ) -> dict[str, Any]:
        """Submit grounded external analysis after matching the confirmed source revision."""
        owner_id = current_user(ctx).id
        return await workflow_call(
            settings,
            lambda svc: svc.submit_analysis(
                owner_id=owner_id,
                workspace_id=workspace_id,
                source_id=source_id,
                expected_revision=expected_revision,
                expected_fingerprint=expected_fingerprint,
                result=result,
            ),
        )

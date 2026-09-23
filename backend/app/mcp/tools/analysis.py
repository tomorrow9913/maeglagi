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
        model: Annotated[str | None, Field(default=None, max_length=160)] = None,
        provider: Annotated[str | None, Field(default=None, max_length=80)] = None,
        agent_name: Annotated[
            str | None, Field(default=None, max_length=120, serialization_alias="agentName")
        ] = None,
    ) -> dict[str, Any]:
        """Store agent-produced analysis. Report provider, model and agent_name for provenance."""
        owner_id = current_user(ctx).id
        submission = await workflow_call(
            settings,
            lambda svc: svc.submit_analysis(
                owner_id=owner_id,
                workspace_id=workspace_id,
                source_id=source_id,
                expected_revision=expected_revision,
                expected_fingerprint=expected_fingerprint,
                result=result,
                provenance={
                    key: value
                    for key, value in {
                        "provider": provider,
                        "model": model,
                        "agentName": agent_name,
                    }.items()
                    if value
                },
            ),
        )
        return {
            **submission,
            "completionMessage": (
                "분석 결과 저장을 완료했습니다. 경고 내용을 확인해 주세요."
                if submission["warnings"]
                else "분석 결과 저장을 완료했습니다."
            ),
        }

"""Keep application failures useful without leaking server internals to agents."""

from collections.abc import Awaitable, Callable
from typing import Any

import sentry_sdk
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from app.core.config import Settings
from app.mcp.context import mcp_session


def json_result(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list):
        return [json_result(item) for item in value]
    if isinstance(value, dict):
        return {key: json_result(item) for key, item in value.items()}
    return value


async def workflow_call(
    settings: Settings,
    operation: Callable[[Any], Awaitable[Any]],
) -> Any:
    from app.modules.agent_workflows.errors import WorkflowError
    from app.modules.agent_workflows.service import AgentWorkflowService

    try:
        async with mcp_session() as session:
            return json_result(await operation(AgentWorkflowService(session, settings)))
    except WorkflowError as exc:
        raise ToolError(f"Workflow rejected: {exc.code}") from None
    except Exception as exc:
        sentry_sdk.capture_message(f"MCP workflow unexpected {type(exc).__name__}", level="error")
        raise ToolError("Workflow unavailable") from None


async def knowledge_call(ctx: Any, operation: Callable[[Any], Awaitable[Any]]) -> Any:
    from app.modules.retrieval.application.agent_knowledge import (
        AgentKnowledgeService,
        KnowledgeAccessError,
    )

    parent = ctx.request_context.request.scope.get("maeglagi_parent_app")
    graph_store = getattr(getattr(parent, "state", None), "graph_store", None)
    try:
        async with mcp_session() as session:
            service = AgentKnowledgeService(session, graph_store)
            return json_result(await operation(service))
    except KnowledgeAccessError as exc:
        raise ToolError(f"Knowledge read rejected: {exc.code}") from None
    except Exception as exc:
        sentry_sdk.capture_message(f"MCP knowledge unexpected {type(exc).__name__}", level="error")
        raise ToolError("Knowledge read unavailable") from None

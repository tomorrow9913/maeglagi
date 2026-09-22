from typing import Any
from uuid import UUID

from asgi_correlation_id import correlation_id
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import AuthUser
from app.modules.workspaces.infrastructure.models import WorkspaceAuditEvent


def add_audit_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor: AuthUser,
    action: str,
    target_type: str,
    target_id: UUID | str | None = None,
    origin: str = "web",
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> WorkspaceAuditEvent:
    event = WorkspaceAuditEvent(
        workspace_id=workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        origin=origin,
        details=details or {},
        request_id=request_id or correlation_id.get(),
    )
    if hasattr(session, "add"):
        session.add(event)
    return event

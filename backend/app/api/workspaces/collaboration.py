from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.workspaces.application.access import normalize_email, workspace_access
from app.modules.workspaces.application.audit import add_audit_event
from app.modules.workspaces.infrastructure.models import (
    Source,
    WorkspaceAuditEvent,
    WorkspaceMember,
)

router = APIRouter(prefix="/workspaces/{workspace_id}")
Session = Annotated[AsyncSession, Depends(get_session)]
Role = Literal["admin", "editor", "viewer"]


class InviteInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Role = "editor"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip()
        if value.count("@") != 1 or any(char.isspace() for char in value):
            raise ValueError("Invalid email")
        local, domain = value.split("@")
        if not local or not domain or "." not in domain:
            raise ValueError("Invalid email")
        return value


class RoleInput(BaseModel):
    role: Role


class MemberResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    user_id: UUID | None = Field(serialization_alias="userId")
    email: str
    role: str
    joined_at: datetime | None = Field(serialization_alias="joinedAt")
    created_at: datetime = Field(serialization_alias="createdAt")


class AuditResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    actor_id: UUID = Field(serialization_alias="actorId")
    actor_email: str | None = Field(serialization_alias="actorEmail")
    action: str
    target_type: str = Field(serialization_alias="targetType")
    target_id: str | None = Field(serialization_alias="targetId")
    origin: str
    details: dict
    request_id: str | None = Field(serialization_alias="requestId")
    created_at: datetime = Field(serialization_alias="createdAt")


def member_response(row: WorkspaceMember) -> MemberResponse:
    return MemberResponse.model_validate(row, from_attributes=True)


@router.get("/members", response_model=list[MemberResponse])
async def list_members(workspace_id: UUID, user: CurrentUser, session: Session):
    await workspace_access(session, workspace_id, user, minimum_role="viewer")
    rows = (
        await session.exec(
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at)
        )
    ).all()
    return [member_response(row) for row in rows]


@router.post("/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    workspace_id: UUID, body: InviteInput, request: Request, user: CurrentUser, session: Session
):
    await workspace_access(session, workspace_id, user, minimum_role="admin")
    email = body.email.strip()
    normalized = normalize_email(email)
    existing = (
        await session.exec(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.email_normalized == normalized,
            )
        )
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Member already invited")
    member = WorkspaceMember(
        workspace_id=workspace_id,
        email=email,
        email_normalized=normalized,
        role=body.role,
        invited_by=user.id,
    )
    session.add(member)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="member.invited",
        target_type="member",
        target_id=member.id,
        details={"email": email, "role": body.role},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    await session.refresh(member)
    return member_response(member)


@router.patch("/members/{member_id}", response_model=MemberResponse)
async def change_role(
    workspace_id: UUID,
    member_id: UUID,
    body: RoleInput,
    request: Request,
    user: CurrentUser,
    session: Session,
):
    await workspace_access(session, workspace_id, user, minimum_role="admin")
    member = await session.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id or member.role == "owner":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    previous = member.role
    member.role = body.role
    session.add(member)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="member.role_changed",
        target_type="member",
        target_id=member.id,
        details={"email": member.email, "before": previous, "after": body.role},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return member_response(member)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: UUID, member_id: UUID, request: Request, user: CurrentUser, session: Session
):
    await workspace_access(session, workspace_id, user, minimum_role="admin")
    member = await session.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id or member.role == "owner":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="member.removed",
        target_type="member",
        target_id=member.id,
        details={"email": member.email, "role": member.role},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.delete(member)
    await session.commit()


@router.get("/audit-events", response_model=list[AuditResponse])
async def audit_events(
    workspace_id: UUID,
    user: CurrentUser,
    session: Session,
    action: str | None = None,
    actor_id: Annotated[UUID | None, Query(alias="actorId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    await workspace_access(session, workspace_id, user, minimum_role="viewer")
    query = select(WorkspaceAuditEvent).where(WorkspaceAuditEvent.workspace_id == workspace_id)
    if action:
        query = query.where(WorkspaceAuditEvent.action == action)
    if actor_id:
        query = query.where(WorkspaceAuditEvent.actor_id == actor_id)
    rows = (
        await session.exec(query.order_by(WorkspaceAuditEvent.created_at.desc()).limit(limit))
    ).all()
    # Older/retried analysis events may predate provenance being copied onto the
    # audit row. The checkpoint is the durable record of the model that actually
    # produced the stored graph, so use it to complete the read response.
    source_ids: list[UUID] = []
    for row in rows:
        if row.action != "analysis.completed" or not row.target_id:
            continue
        try:
            source_ids.append(UUID(row.target_id))
        except ValueError:
            continue
    sources = (
        (
            await session.exec(
                select(Source).where(Source.workspace_id == workspace_id, Source.id.in_(source_ids))  # type: ignore[attr-defined]
            )
        ).all()
        if source_ids
        else []
    )
    provenance_by_source = {
        str(source.id): (source.analysis_checkpoint or {}).get("provenance", {})
        for source in sources
    }
    responses: list[AuditResponse] = []
    for row in rows:
        response = AuditResponse.model_validate(row, from_attributes=True)
        provenance = provenance_by_source.get(row.target_id or "", {})
        if isinstance(provenance, dict):
            response.details = {**provenance, **response.details}
        responses.append(response)
    return responses

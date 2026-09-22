from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import AuthUser
from app.modules.workspaces.infrastructure.models import Workspace, WorkspaceMember

ROLE_LEVEL = {"viewer": 10, "editor": 20, "admin": 30, "owner": 40}


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace: Workspace
    member: WorkspaceMember

    @property
    def data_owner_id(self) -> UUID:
        return self.workspace.owner_id


def normalize_email(email: str) -> str:
    return email.strip().casefold()


async def claim_pending_memberships(session: AsyncSession, user: AuthUser) -> None:
    if not user.email:
        return
    normalized = normalize_email(user.email)
    rows = (
        await session.exec(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id.is_(None),
                WorkspaceMember.email_normalized == normalized,
            )
        )
    ).all()
    for member in rows:
        member.user_id = user.id
        member.email = user.email
        member.joined_at = datetime.now(UTC)
        session.add(member)
    if rows:
        await session.commit()


async def workspace_access(
    session: AsyncSession,
    workspace_id: UUID,
    user: AuthUser,
    *,
    minimum_role: str = "viewer",
) -> WorkspaceAccess:
    await claim_pending_memberships(session, user)
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    # Owners remain authorized while the membership backfill rolls out and this
    # also keeps legacy fixtures compatible without querying the new table.
    if workspace.owner_id == user.id:
        email = user.email or ""
        return WorkspaceAccess(
            workspace=workspace,
            member=WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                email=email,
                email_normalized=normalize_email(email),
                role="owner",
                invited_by=user.id,
                joined_at=datetime.now(UTC),
            ),
        )
    identities = [WorkspaceMember.user_id == user.id]
    if user.email:
        identities.append(WorkspaceMember.email_normalized == normalize_email(user.email))
    result = await session.exec(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            or_(*identities),
        )
    )
    first = getattr(result, "first", None)
    if callable(first):
        candidate = first()
    else:
        rows = result.all() if callable(getattr(result, "all", None)) else list(result)
        candidate = rows[0] if rows else None
    member = candidate if isinstance(candidate, WorkspaceMember) else None
    if member is None or ROLE_LEVEL[member.role] < ROLE_LEVEL[minimum_role]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return WorkspaceAccess(workspace=workspace, member=member)

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth.models import AuthUser
from app.modules.workspaces.application.access import workspace_access
from app.modules.workspaces.infrastructure.models import Workspace, WorkspaceMember


class Result:
    def __init__(self, member: WorkspaceMember | None) -> None:
        self.member = member

    def first(self) -> WorkspaceMember | None:
        return self.member


class Session:
    def __init__(self, workspace: Workspace, member: WorkspaceMember | None) -> None:
        self.workspace = workspace
        self.member = member

    async def get(self, model: type, identifier):
        assert model is Workspace
        return self.workspace if identifier == self.workspace.id else None

    async def exec(self, _statement: object) -> Result:
        return Result(self.member)


@pytest.mark.asyncio
async def test_shared_member_role_controls_write_access_and_preserves_data_owner() -> None:
    owner_id, member_id = uuid4(), uuid4()
    workspace = Workspace(owner_id=owner_id, name="Shared")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=member_id,
        email="member@example.com",
        email_normalized="member@example.com",
        role="viewer",
        invited_by=owner_id,
    )
    session = Session(workspace, member)
    access = await workspace_access(session, workspace.id, AuthUser(id=member_id))  # type: ignore[arg-type]
    assert access.data_owner_id == owner_id
    assert access.member.role == "viewer"

    with pytest.raises(HTTPException) as denied:
        await workspace_access(  # type: ignore[arg-type]
            session, workspace.id, AuthUser(id=member_id), minimum_role="editor"
        )
    assert denied.value.status_code == 404

    member.role = "editor"
    access = await workspace_access(  # type: ignore[arg-type]
        session, workspace.id, AuthUser(id=member_id), minimum_role="editor"
    )
    assert access.member.role == "editor"


@pytest.mark.asyncio
async def test_non_member_cannot_discover_workspace() -> None:
    workspace = Workspace(owner_id=uuid4(), name="Private")
    with pytest.raises(HTTPException) as denied:
        await workspace_access(  # type: ignore[arg-type]
            Session(workspace, None), workspace.id, AuthUser(id=uuid4())
        )
    assert denied.value.status_code == 404

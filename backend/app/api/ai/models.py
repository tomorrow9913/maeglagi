from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.modules.context_engine.application.model_catalog import (
    has_indexed_chunks,
    options_for_key,
    options_for_workspace,
)
from app.modules.context_engine.application.model_roles import (
    ROLE_ORDER,
    ModelOption,
    ModelRole,
    invalid_selections,
    selection_of,
)
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.workspaces.infrastructure.models import Workspace

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class RoleModelsResponse(BaseModel):
    role: str
    options: list[ModelOption]
    selected: ModelOption | None
    # Fixed for good: the embedding model cannot change once sources are indexed.
    locked: bool


class WorkspaceModelsResponse(BaseModel):
    roles: list[RoleModelsResponse]


class KeyModelsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    api_key: str = Field(min_length=1, validation_alias="apiKey")


class UpdateModelsRequest(BaseModel):
    selections: dict[str, ModelOption]


def _response(
    options: dict[ModelRole, list[ModelOption]],
    model_settings: dict[str, object] | None,
    locked: set[ModelRole],
) -> WorkspaceModelsResponse:
    roles = []
    for role in ROLE_ORDER:
        chosen = selection_of(model_settings, role)
        roles.append(
            RoleModelsResponse(
                role=role.value,
                options=options[role],
                # A choice the key no longer offers is shown as unset rather than as a dead option.
                selected=chosen if chosen in options[role] else None,
                locked=role in locked,
            )
        )
    return WorkspaceModelsResponse(roles=roles)


async def _owned_workspace(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession
) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


@router.post("/llm-keys/models", response_model=WorkspaceModelsResponse)
async def list_key_models(body: KeyModelsRequest, _user: CurrentUser) -> WorkspaceModelsResponse:
    """The models a key can use, sorted into jobs, for choosing before a workspace exists."""
    valid, message = await validate_provider_credential(body.provider, body.api_key)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    return _response(await options_for_key(body.provider, body.api_key), None, set())


@router.get("/workspaces/{workspace_id}/ai/models", response_model=WorkspaceModelsResponse)
async def get_workspace_models(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> WorkspaceModelsResponse:
    workspace = await _owned_workspace(workspace_id, user, session)
    options = await options_for_workspace(session, workspace.id, user.id)
    locked = {ModelRole.EMBEDDING} if await has_indexed_chunks(session, workspace.id) else set()
    return _response(options, workspace.model_settings, locked)


@router.put("/workspaces/{workspace_id}/ai/models", response_model=WorkspaceModelsResponse)
async def update_workspace_models(
    workspace_id: UUID,
    body: UpdateModelsRequest,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
) -> WorkspaceModelsResponse:
    workspace = await _owned_workspace(workspace_id, user, session)
    options = await options_for_workspace(session, workspace.id, user.id)
    problems = invalid_selections(body.selections, options)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))

    locked = {ModelRole.EMBEDDING} if await has_indexed_chunks(session, workspace.id) else set()
    requested = body.selections.get(ModelRole.EMBEDDING.value)
    if requested is not None and ModelRole.EMBEDDING in locked:
        current = selection_of(workspace.model_settings, ModelRole.EMBEDDING)
        # A workspace that never chose embedded with the deployment default; recording that
        # model is allowed, anything else would mix incompatible vectors.
        unchanged = requested == current or (
            current is None and requested.model == settings.embedding_model
        )
        if not unchanged:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "이미 색인된 소스가 있어 임베딩 모델을 바꿀 수 없습니다. 바꾸면 기존 검색 결과와 "
                "새 결과가 섞여 품질이 떨어집니다.",
            )

    workspace.model_settings = {
        **workspace.model_settings,
        **{role: choice.model_dump() for role, choice in body.selections.items()},
    }
    session.add(workspace)
    await session.commit()
    return _response(options, workspace.model_settings, locked)

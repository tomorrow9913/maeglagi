from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.credentials import _base_url, _lock_account
from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
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
from app.modules.context_engine.infrastructure.provider_registry import provider_registry
from app.modules.ingestion.application.pipeline import IngestionError, IngestionPipeline
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class RoleModelsResponse(BaseModel):
    role: str
    options: list[ModelOption]
    selected: ModelOption | None
    # Fixed for good. Only the embedding model is: it is chosen when the workspace is created,
    # because vectors of two models cannot be searched together. LLM models change freely.
    locked: bool


class WorkspaceModelsResponse(BaseModel):
    roles: list[RoleModelsResponse]


class KeyModelsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str | None = None
    credential_id: UUID | None = Field(default=None, validation_alias="credentialId")
    # Ollama uses the administrator configured server address and no user key.
    api_key: str = Field(default="", validation_alias="apiKey")
    base_url: str | None = Field(default=None, validation_alias="baseUrl")


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
                # The stored choice remains visible even when browsing another provider or
                # when a key no longer offers it. In particular, never hide a locked embedding.
                selected=chosen,
                locked=role in locked,
            )
        )
    return WorkspaceModelsResponse(roles=roles)


async def _locked_roles(session: AsyncSession, workspace: Workspace) -> set[ModelRole]:
    """Embedding is fixed once chosen, or once anything has been embedded with the default."""
    chosen = selection_of(workspace.model_settings, ModelRole.EMBEDDING) is not None
    if chosen or await has_indexed_chunks(session, workspace.id):
        return {ModelRole.EMBEDDING}
    return set()


async def _owned_workspace(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession, *, for_update: bool = False
) -> Workspace:
    # The model writer shares this lock with credential mutations. Refresh the
    # identity map so selections and key options are read after earlier writers.
    workspace = (
        await session.get(Workspace, workspace_id, with_for_update=True, populate_existing=True)
        if for_update
        else await session.get(Workspace, workspace_id)
    )
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


@router.post("/llm-keys/models", response_model=WorkspaceModelsResponse)
async def list_key_models(
    body: KeyModelsRequest, user: CurrentUser, session: Session
) -> WorkspaceModelsResponse:
    """The models a key can use, sorted into jobs, for choosing before a workspace exists."""
    if body.credential_id is not None:
        credential = await session.get(ProviderCredential, body.credential_id)
        if credential is None or credential.owner_id != user.id or credential.status != "active":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
        if body.provider is not None and body.provider != credential.provider:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provider mismatch")
        provider = credential.provider
        base_url = credential.base_url
        try:
            key = await resolve_credential_secret(session, credential)
        except CredentialUnavailableError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Saved credential is unavailable"
            ) from exc
    else:
        if body.provider is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "credentialId or provider is required"
            )
        provider = body.provider
        base_url = _base_url(provider, body.base_url)
        key = body.api_key
    valid, message = await (
        validate_provider_credential(provider, key, base_url)
        if provider == "ollama"
        else validate_provider_credential(provider, key)
    )
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    options = await (
        options_for_key(provider, key, base_url, credential.id if body.credential_id else None)
        if provider == "ollama"
        else options_for_key(provider, key, credential_id=credential.id)
        if body.credential_id is not None
        else options_for_key(provider, key)
    )
    return _response(options, None, set())


@router.get("/workspaces/{workspace_id}/ai/models", response_model=WorkspaceModelsResponse)
async def get_workspace_models(
    workspace_id: UUID, user: CurrentUser, session: Session, provider: str | None = None
) -> WorkspaceModelsResponse:
    workspace = await _owned_workspace(workspace_id, user, session)
    if provider is not None and provider not in {adapter.id for adapter in provider_registry.all()}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown provider")
    options = await options_for_workspace(session, workspace.id, user.id, provider)
    return _response(options, workspace.model_settings, await _locked_roles(session, workspace))


@router.put("/workspaces/{workspace_id}/ai/models", response_model=WorkspaceModelsResponse)
async def update_workspace_models(
    workspace_id: UUID,
    body: UpdateModelsRequest,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
) -> WorkspaceModelsResponse:
    await _lock_account(session, user.id)
    workspace = await _owned_workspace(workspace_id, user, session, for_update=True)
    options = await options_for_workspace(session, workspace.id, user.id)
    problems = invalid_selections(body.selections, options)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))

    locked = await _locked_roles(session, workspace)
    requested = body.selections.get(ModelRole.EMBEDDING.value)
    if requested is not None and ModelRole.EMBEDDING in locked:
        current = selection_of(workspace.model_settings, ModelRole.EMBEDDING)
        unchanged = requested == current
        if current is None:
            # Legacy indexed chunks have no stored selection. Resolve the same key and flat
            # embedding model used by ingestion before accepting a selection for those vectors.
            try:
                legacy = await IngestionPipeline(settings).provider_with_model(
                    session,
                    workspace_id=workspace.id,
                    owner_id=user.id,
                    role=ModelRole.EMBEDDING,
                )
                unchanged = requested == ModelOption(provider=legacy.adapter.id, model=legacy.model)
            except IngestionError:
                unchanged = False
        if not unchanged:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "임베딩 모델은 워크스페이스를 만들 때 정해지며 바꿀 수 없습니다. 모델마다 벡터가 "
                "달라 바꾸면 이미 색인한 소스와 함께 검색할 수 없습니다.",
            )

    workspace.model_settings = {
        **workspace.model_settings,
        **{
            role: choice.model_dump(mode="json", by_alias=True)
            for role, choice in body.selections.items()
        },
    }
    session.add(workspace)
    await session.commit()
    return _response(options, workspace.model_settings, locked)

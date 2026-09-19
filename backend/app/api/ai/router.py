from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.ai.schemas import (
    ProviderCatalogItem,
    ProviderChatRequest,
    ProviderEmbeddingRequest,
    ProviderStructuredOutputRequest,
)
from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
from app.core.database import get_session
from app.modules.context_engine.application.provider import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ProviderAdapter,
    StructuredOutputRequest,
    StructuredOutputResponse,
)
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.context_engine.infrastructure.provider_registry import (
    adapter_for_credential,
    provider_registry,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

router = APIRouter(prefix="/workspaces/{workspace_id}/ai")
Session = Annotated[AsyncSession, Depends(get_session)]


async def _workspace_credentials(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession
) -> list[ProviderCredential]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    result = await session.exec(
        select(ProviderCredential).where(
            ProviderCredential.owner_id == user.id,
            ProviderCredential.status == "active",
        )
    )
    return list(result.all())


async def _provider_with_credential(
    provider_id: str,
    capability: str,
    credential_label: str | None,
    credential_id: str | None,
    credentials: list[ProviderCredential],
    session: AsyncSession,
) -> tuple[ProviderAdapter, str]:
    credential = next(
        (
            item
            for item in credentials
            if item.provider == provider_id
            and (credential_id is None or str(item.id) == credential_id)
            and (credential_label is None or item.label == credential_label)
            and (credential_label is not None or credential_id is not None or item.is_default)
        ),
        None,
    )
    if credential is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "사용 가능한 API key가 없습니다.")
    adapter = adapter_for_credential(credential)
    if adapter is None or capability not in adapter.capabilities:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{capability}을 지원하지 않는 provider입니다.",
        )
    try:
        api_key = await resolve_credential_secret(session, credential)
    except CredentialUnavailableError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "저장된 API key를 사용할 수 없습니다."
        ) from exc
    return adapter, api_key


@router.get("/providers", response_model=list[ProviderCatalogItem])
async def list_available_providers(
    workspace_id: UUID,
    user: CurrentUser,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ProviderCatalogItem]:
    credentials = await _workspace_credentials(workspace_id, user, session)
    items: list[ProviderCatalogItem] = []
    for adapter in provider_registry.all():
        matching = [credential for credential in credentials if credential.provider == adapter.id]
        models: set[str] = set()
        for credential in matching:
            try:
                api_key = await resolve_credential_secret(session, credential)
                configured_adapter = (
                    adapter_for_credential(credential)
                    if credential.provider == "ollama"
                    else adapter
                )
                infos = (
                    await configured_adapter.list_model_infos(api_key) if configured_adapter else []
                )
                today = date.today()
                models.update(
                    info.id
                    for info in infos
                    if info.shutdown_date is None or info.shutdown_date > today
                )
            except (ProviderError, CredentialUnavailableError):
                continue
        items.append(
            ProviderCatalogItem(
                id=adapter.id,
                display_name=adapter.display_name,
                capabilities=list(adapter.capabilities),
                configured=bool(matching),
                auth_mode="optionalApiKey" if adapter.id == "ollama" else "apiKey",
                requires_base_url=adapter.id == "ollama",
                models=sorted(models),
                default_models=settings.provider_default_models.get(adapter.id, {}),
            )
        )
    return items


@router.post("/chat", response_model=ChatResponse)
async def chat(
    workspace_id: UUID, body: ProviderChatRequest, user: CurrentUser, session: Session
) -> ChatResponse:
    credentials = await _workspace_credentials(workspace_id, user, session)
    adapter, api_key = await _provider_with_credential(
        body.provider, "chat", body.credential_label, body.credential_id, credentials, session
    )
    request = ChatRequest(
        messages=body.messages,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        provider_options=body.provider_options,
    )
    try:
        return await adapter.chat(request, api_key)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/embeddings", response_model=EmbeddingResponse)
async def embedding(
    workspace_id: UUID, body: ProviderEmbeddingRequest, user: CurrentUser, session: Session
) -> EmbeddingResponse:
    credentials = await _workspace_credentials(workspace_id, user, session)
    adapter, api_key = await _provider_with_credential(
        body.provider, "embedding", body.credential_label, body.credential_id, credentials, session
    )
    request = EmbeddingRequest(
        input=body.input,
        model=body.model,
        dimensions=body.dimensions,
        provider_options=body.provider_options,
    )
    try:
        return await adapter.embedding(request, api_key)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/structured-output", response_model=StructuredOutputResponse)
async def structured_output(
    workspace_id: UUID,
    body: ProviderStructuredOutputRequest,
    user: CurrentUser,
    session: Session,
) -> StructuredOutputResponse:
    credentials = await _workspace_credentials(workspace_id, user, session)
    adapter, api_key = await _provider_with_credential(
        body.provider,
        "structuredOutput",
        body.credential_label,
        body.credential_id,
        credentials,
        session,
    )
    request = StructuredOutputRequest(
        messages=body.messages,
        model=body.model,
        schema_name=body.schema_name,
        json_schema=body.json_schema,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        provider_options=body.provider_options,
    )
    try:
        return await adapter.structured_output(request, api_key)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

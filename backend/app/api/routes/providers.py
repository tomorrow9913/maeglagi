from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import CurrentUser
from app.core.credentials import decrypt_credential
from app.core.database import get_session
from app.modules.context_engine.application.provider import ChatRequest, ChatResponse
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.context_engine.infrastructure.provider_registry import provider_registry
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace
from app.schemas.providers import ProviderCatalogItem, ProviderChatRequest

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
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == user.id,
            ProviderCredential.status == "active",
        )
    )
    return list(result.all())


@router.get("/providers", response_model=list[ProviderCatalogItem])
async def list_available_providers(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> list[ProviderCatalogItem]:
    credentials = await _workspace_credentials(workspace_id, user, session)
    by_provider = {credential.provider: credential for credential in credentials}
    items: list[ProviderCatalogItem] = []
    for adapter in provider_registry.all():
        credential = by_provider.get(adapter.id)
        models: list[str] = []
        if credential is not None:
            try:
                models = await adapter.list_models(decrypt_credential(credential.encrypted_secret))
            except (ProviderError, ValueError):
                models = []
        items.append(
            ProviderCatalogItem(
                id=adapter.id,
                display_name=adapter.display_name,
                capabilities=list(adapter.capabilities),
                configured=credential is not None,
                models=models,
            )
        )
    return items


@router.post("/chat", response_model=ChatResponse)
async def chat(
    workspace_id: UUID, body: ProviderChatRequest, user: CurrentUser, session: Session
) -> ChatResponse:
    credentials = await _workspace_credentials(workspace_id, user, session)
    adapter = provider_registry.get(body.provider)
    if adapter is None or "chat" not in adapter.capabilities:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "지원하지 않는 provider입니다.")
    credential = next(
        (
            item
            for item in credentials
            if item.provider == body.provider
            and (body.credential_label is None or item.label == body.credential_label)
            and (body.credential_label is not None or item.is_default)
        ),
        None,
    )
    if credential is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "사용 가능한 API key가 없습니다.")
    request = ChatRequest(
        messages=body.messages,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        provider_options=body.provider_options,
    )
    try:
        return await adapter.chat(request, decrypt_credential(credential.encrypted_secret))
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

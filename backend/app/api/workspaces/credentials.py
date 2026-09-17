from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.schemas import (
    CredentialInput,
    CredentialResponse,
    CredentialValidation,
)
from app.auth import CurrentUser
from app.core.credentials import credential_vault, store_credential_secret
from app.core.database import get_session
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


def _response(credential: ProviderCredential) -> CredentialResponse:
    return CredentialResponse.model_validate(credential, from_attributes=True)


async def _owned_workspace(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession
) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


@router.post("/llm-keys/validate", response_model=CredentialValidation)
async def validate_key(body: CredentialInput, _user: CurrentUser) -> CredentialValidation:
    valid, message = await validate_provider_credential(body.provider, body.api_key)
    return CredentialValidation(valid=valid, message=message)


@router.get(
    "/workspaces/{workspace_id}/provider-credentials",
    response_model=list[CredentialResponse],
)
async def list_credentials(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> list[CredentialResponse]:
    await _owned_workspace(workspace_id, user, session)
    result = await session.exec(
        select(ProviderCredential)
        .where(
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == user.id,
        )
        .order_by(ProviderCredential.created_at)
    )
    return [_response(item) for item in result.all()]


@router.get("/workspaces/{workspace_id}/llm-key", response_model=CredentialResponse | None)
async def get_default_credential(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> CredentialResponse | None:
    await _owned_workspace(workspace_id, user, session)
    result = await session.exec(
        select(ProviderCredential).where(
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == user.id,
            ProviderCredential.is_default.is_(True),
        )
    )
    credential = result.first()
    return _response(credential) if credential else None


@router.put("/workspaces/{workspace_id}/llm-key", response_model=CredentialResponse)
async def upsert_default_credential(
    workspace_id: UUID,
    body: CredentialInput,
    user: CurrentUser,
    session: Session,
) -> CredentialResponse:
    await _owned_workspace(workspace_id, user, session)
    valid, message = await validate_provider_credential(body.provider, body.api_key)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)

    existing_result = await session.exec(
        select(ProviderCredential).where(
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == user.id,
        )
    )
    credentials = list(existing_result.all())
    credential = next(
        (
            item
            for item in credentials
            if item.provider == body.provider and item.label == body.label
        ),
        None,
    )
    for item in credentials:
        item.is_default = False
        session.add(item)
    await session.flush()

    now = datetime.now(UTC)
    if credential is None:
        credential = ProviderCredential(
            workspace_id=workspace_id,
            owner_id=user.id,
            provider=body.provider,
            label=body.label,
            key_hint=body.api_key[-4:],
            is_default=True,
            updated_at=now,
        )
        credential.vault_secret_id = await store_credential_secret(
            session,
            secret=body.api_key,
            credential_id=credential.id,
            workspace_id=workspace_id,
            provider=body.provider,
        )
    else:
        if credential.vault_secret_id is None:
            credential.vault_secret_id = await store_credential_secret(
                session,
                secret=body.api_key,
                credential_id=credential.id,
                workspace_id=workspace_id,
                provider=body.provider,
            )
        else:
            await credential_vault.update(
                session, secret_id=credential.vault_secret_id, secret=body.api_key
            )
        credential.encrypted_secret = None
        credential.key_hint = body.api_key[-4:]
        credential.status = "active"
        credential.is_default = True
        credential.updated_at = now
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return _response(credential)

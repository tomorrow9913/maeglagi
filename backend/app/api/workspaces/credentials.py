from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.schemas import (
    CredentialInput,
    CredentialResponse,
    CredentialRotation,
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
    workspace_id: UUID, user: CurrentUser, session: AsyncSession, *, for_update: bool = False
) -> Workspace:
    # All credential writers lock the parent row before reading credentials. This
    # serializes label checks, default transitions, rotation, and deletion even
    # when no credential row exists yet to lock.
    workspace = (
        await session.get(
            Workspace, workspace_id, with_for_update=True, populate_existing=True
        )
        if for_update
        else await session.get(Workspace, workspace_id)
    )
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


async def _owned_credential(
    workspace_id: UUID, credential_id: UUID, user: CurrentUser, session: AsyncSession
) -> ProviderCredential:
    credential = await session.get(ProviderCredential, credential_id)
    if (
        credential is None
        or credential.workspace_id != workspace_id
        or credential.owner_id != user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    return credential


async def _workspace_credentials(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession
) -> list[ProviderCredential]:
    result = await session.exec(
        select(ProviderCredential)
        .where(
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == user.id,
        )
        .order_by(ProviderCredential.created_at)
    )
    return list(result.all())


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
    return [_response(item) for item in await _workspace_credentials(workspace_id, user, session)]


@router.post(
    "/workspaces/{workspace_id}/provider-credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_credential(
    workspace_id: UUID, body: CredentialInput, user: CurrentUser, session: Session
) -> CredentialResponse:
    await _owned_workspace(workspace_id, user, session, for_update=True)
    valid, message = await validate_provider_credential(body.provider, body.api_key)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    credentials = await _workspace_credentials(workspace_id, user, session)
    if any(item.provider == body.provider and item.label == body.label for item in credentials):
        raise HTTPException(status.HTTP_409_CONFLICT, "Credential label already exists")
    credential = ProviderCredential(
        workspace_id=workspace_id,
        owner_id=user.id,
        provider=body.provider,
        label=body.label,
        key_hint=body.api_key[-4:],
        is_default=False,
    )
    credential.vault_secret_id = await store_credential_secret(
        session,
        secret=body.api_key,
        credential_id=credential.id,
        workspace_id=workspace_id,
        provider=body.provider,
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.put(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}",
    response_model=CredentialResponse,
)
async def rotate_credential(
    workspace_id: UUID,
    credential_id: UUID,
    body: CredentialRotation,
    user: CurrentUser,
    session: Session,
) -> CredentialResponse:
    await _owned_workspace(workspace_id, user, session, for_update=True)
    credential = await _owned_credential(workspace_id, credential_id, user, session)
    valid, message = await validate_provider_credential(credential.provider, body.api_key)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    if credential.vault_secret_id is None:
        credential.vault_secret_id = await store_credential_secret(
            session,
            secret=body.api_key,
            credential_id=credential.id,
            workspace_id=workspace_id,
            provider=credential.provider,
        )
    else:
        await credential_vault.update(
            session, secret_id=credential.vault_secret_id, secret=body.api_key
        )
    credential.encrypted_secret = None
    credential.key_hint = body.api_key[-4:]
    credential.status = "active"
    credential.updated_at = datetime.now(UTC)
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.put(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}/default",
    response_model=CredentialResponse,
)
async def choose_default_credential(
    workspace_id: UUID, credential_id: UUID, user: CurrentUser, session: Session
) -> CredentialResponse:
    await _owned_workspace(workspace_id, user, session, for_update=True)
    credential = await _owned_credential(workspace_id, credential_id, user, session)
    if credential.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Credential is not active")
    for item in await _workspace_credentials(workspace_id, user, session):
        if item.id != credential.id and item.is_default:
            item.is_default = False
            session.add(item)
    # The partial unique index permits only one default. Flush the cleared row first.
    await session.flush()
    credential.is_default = True
    credential.updated_at = datetime.now(UTC)
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.delete(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_credential(
    workspace_id: UUID, credential_id: UUID, user: CurrentUser, session: Session
) -> None:
    workspace = await _owned_workspace(workspace_id, user, session, for_update=True)
    credential = await _owned_credential(workspace_id, credential_id, user, session)
    credentials = await _workspace_credentials(workspace_id, user, session)
    if credential.is_default and len(credentials) > 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Choose another default before deletion")
    selected_providers = {
        selection.get("provider")
        for selection in (workspace.model_settings or {}).values()
        if isinstance(selection, dict)
    }
    if credential.provider in selected_providers and not any(
        item.id != credential.id
        and item.provider == credential.provider
        and item.status == "active"
        for item in credentials
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the last active credential for a selected model provider",
        )
    if credential.vault_secret_id is not None:
        await credential_vault.delete(session, secret_id=credential.vault_secret_id)
    await session.delete(credential)
    await session.commit()


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
    await _owned_workspace(workspace_id, user, session, for_update=True)
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
    # Registering or rotating a key changes credentials only. Model choices are an
    # independent workspace setting, including roles the user has not selected yet.
    await session.commit()
    await session.refresh(credential)
    return _response(credential)

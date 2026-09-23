from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.schemas import (
    CredentialInput,
    CredentialResponse,
    CredentialRotation,
    CredentialValidation,
)
from app.auth import CurrentUser
from app.core.credentials import (
    credential_vault,
    resolve_credential_secret,
    store_credential_secret,
)
from app.core.database import get_session
from app.core.ollama_endpoint import normalize_ollama_url
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.workspaces.application.access import workspace_access
from app.modules.workspaces.application.audit import add_audit_event
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

router = APIRouter()


def _credential_key(provider: str, value: str | None) -> str:
    if provider == "ollama":
        return value or ""
    if not value:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "API key is required")
    return value


def _base_url(provider: str, value: str | None, *, existing: str | None = None) -> str | None:
    if provider != "ollama":
        if value is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "baseUrl is only for Ollama")
        return None
    if value is None:
        if existing is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ollama baseUrl is required")
        return existing
    try:
        return normalize_ollama_url(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid Ollama baseUrl") from exc


def _key_hint(provider: str, key: str) -> str:
    return ("configured" if key else "none") if provider == "ollama" else key[-4:]


async def _validate(provider: str, key: str, base_url: str | None) -> tuple[bool, str]:
    return await (
        validate_provider_credential(provider, key, base_url)
        if provider == "ollama"
        else validate_provider_credential(provider, key)
    )


async def _set_secret(session: AsyncSession, credential: ProviderCredential, key: str) -> None:
    if key:
        if credential.vault_secret_id is None:
            credential.vault_secret_id = await store_credential_secret(
                session,
                secret=key,
                credential_id=credential.id,
                workspace_id=credential.workspace_id,
                provider=credential.provider,
            )
        else:
            await credential_vault.update(session, secret_id=credential.vault_secret_id, secret=key)
    elif credential.vault_secret_id is not None:
        await credential_vault.delete(session, secret_id=credential.vault_secret_id)
        credential.vault_secret_id = None
    credential.encrypted_secret = None
    credential.key_hint = _key_hint(credential.provider, key)


Session = Annotated[AsyncSession, Depends(get_session)]


async def _lock_account(session: AsyncSession, owner_id: UUID) -> None:
    """Serialize account credential mutations with workspace model selection writes."""
    if isinstance(session, AsyncSession) and session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(owner_id.bytes[:8], "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _response(credential: ProviderCredential) -> CredentialResponse:
    return CredentialResponse.model_validate(credential, from_attributes=True)


async def _owned_workspace(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession, *, for_update: bool = False
) -> Workspace:
    # All credential writers lock the parent row before reading credentials. This
    # serializes label checks, default transitions, rotation, and deletion even
    # when no credential row exists yet to lock.
    access = await workspace_access(session, workspace_id, user)
    if not for_update:
        return access.workspace
    workspace = await session.get(
        Workspace, workspace_id, with_for_update=True, populate_existing=True
    )
    assert workspace is not None
    return workspace


async def _owned_credential(
    workspace_id: UUID | None, credential_id: UUID, user: CurrentUser, session: AsyncSession
) -> ProviderCredential:
    credential = await session.get(ProviderCredential, credential_id)
    if credential is None or credential.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    if workspace_id is None and credential.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    return credential


async def _workspace_credentials(
    workspace_id: UUID | None, user: CurrentUser, session: AsyncSession
) -> list[ProviderCredential]:
    statement = select(ProviderCredential)
    if workspace_id is None:
        statement = statement.where(
            ProviderCredential.owner_id == user.id,
            ProviderCredential.workspace_id.is_(None),
        )
    else:
        statement = statement.where(ProviderCredential.workspace_id == workspace_id)
    result = await session.exec(statement.order_by(ProviderCredential.created_at))
    return list(result.all())


@router.post("/llm-keys/validate", response_model=CredentialValidation)
async def validate_key(body: CredentialInput, _user: CurrentUser) -> CredentialValidation:
    try:
        key = _credential_key(body.provider, body.api_key)
        base_url = _base_url(body.provider, body.base_url)
    except HTTPException as exc:
        return CredentialValidation(valid=False, message=str(exc.detail))
    valid, message = await _validate(body.provider, key, base_url)
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
    workspace_id: UUID | None, body: CredentialInput, user: CurrentUser, session: Session
) -> CredentialResponse:
    await _lock_account(session, user.id)
    if workspace_id is not None:
        access = await workspace_access(session, workspace_id, user, minimum_role="admin")
        await _owned_workspace(access.workspace.id, user, session, for_update=True)
    key = _credential_key(body.provider, body.api_key)
    base_url = _base_url(body.provider, body.base_url)
    valid, message = await _validate(body.provider, key, base_url)
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
        key_hint=_key_hint(body.provider, key),
        base_url=base_url,
        is_default=not any(item.is_default for item in credentials),
    )
    if key:
        await _set_secret(session, credential, key)
    session.add(credential)
    if workspace_id is not None:
        add_audit_event(
            session,
            workspace_id=workspace_id,
            actor=user,
            action="credential.created",
            target_type="provider_credential",
            target_id=credential.id,
            details={"provider": credential.provider, "label": credential.label},
        )
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.put(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}",
    response_model=CredentialResponse,
)
async def rotate_credential(
    workspace_id: UUID | None,
    credential_id: UUID,
    body: CredentialRotation,
    user: CurrentUser,
    session: Session,
) -> CredentialResponse:
    await _lock_account(session, user.id)
    if workspace_id is not None:
        access = await workspace_access(session, workspace_id, user, minimum_role="admin")
        await _owned_workspace(access.workspace.id, user, session, for_update=True)
    credential = await _owned_credential(workspace_id, credential_id, user, session)
    # Missing Ollama fields preserve the existing connection and secret. Legacy rows
    # without base_url continue to use the administrator endpoint.
    base_url = (
        _base_url(credential.provider, body.base_url, existing=credential.base_url)
        if body.base_url is not None
        else credential.base_url
    )
    key = (
        await resolve_credential_secret(session, credential)
        if credential.provider == "ollama" and "api_key" not in body.model_fields_set
        else _credential_key(credential.provider, body.api_key)
    )
    valid, message = await _validate(credential.provider, key, base_url)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    if credential.provider != "ollama" or "api_key" in body.model_fields_set:
        await _set_secret(session, credential, key)
    credential.base_url = base_url
    credential.status = "active"
    credential.updated_at = datetime.now(UTC)
    session.add(credential)
    if workspace_id is not None:
        add_audit_event(
            session,
            workspace_id=workspace_id,
            actor=user,
            action="credential.rotated",
            target_type="provider_credential",
            target_id=credential.id,
            details={"provider": credential.provider, "label": credential.label},
        )
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.put(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}/default",
    response_model=CredentialResponse,
)
async def choose_default_credential(
    workspace_id: UUID | None, credential_id: UUID, user: CurrentUser, session: Session
) -> CredentialResponse:
    await _lock_account(session, user.id)
    if workspace_id is not None:
        access = await workspace_access(session, workspace_id, user, minimum_role="admin")
        await _owned_workspace(access.workspace.id, user, session, for_update=True)
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
    if workspace_id is not None:
        add_audit_event(
            session,
            workspace_id=workspace_id,
            actor=user,
            action="credential.default_changed",
            target_type="provider_credential",
            target_id=credential.id,
            details={"provider": credential.provider, "label": credential.label},
        )
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.delete(
    "/workspaces/{workspace_id}/provider-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_credential(
    workspace_id: UUID | None, credential_id: UUID, user: CurrentUser, session: Session
) -> None:
    await _lock_account(session, user.id)
    workspace = None
    if workspace_id is not None:
        await workspace_access(session, workspace_id, user, minimum_role="admin")
        workspace = await _owned_workspace(workspace_id, user, session, for_update=True)
    credential = await _owned_credential(workspace_id, credential_id, user, session)
    credentials = await _workspace_credentials(workspace_id, user, session)
    if credential.is_default and len(credentials) > 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Choose another default before deletion")
    if workspace_id is None:
        workspace_rows = (
            await session.exec(select(Workspace).where(Workspace.owner_id == user.id))
        ).all()
        workspaces = [item for item in workspace_rows if isinstance(item, Workspace)]
    else:
        workspaces = [workspace] if workspace is not None else []
    selections = [
        selection
        for owned in workspaces
        for selection in (owned.model_settings or {}).values()
        if isinstance(selection, dict)
    ]
    selected_providers = {selection.get("provider") for selection in selections}
    selected_ids = {selection.get("credentialId") for selection in selections}
    if str(credential.id) in selected_ids:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This credential is selected by a workspace model",
        )
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
    if workspace_id is not None:
        add_audit_event(
            session,
            workspace_id=workspace_id,
            actor=user,
            action="credential.deleted",
            target_type="provider_credential",
            target_id=credential.id,
            details={"provider": credential.provider, "label": credential.label},
        )
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
            ProviderCredential.is_default.is_(True),
        )
    )
    credential = result.first()
    if credential is None:
        fallback = await session.exec(
            select(ProviderCredential).where(
                ProviderCredential.workspace_id.is_(None),
                ProviderCredential.owner_id == user.id,
                ProviderCredential.is_default.is_(True),
            )
        )
        credential = fallback.first()
    return _response(credential) if credential else None


@router.put("/workspaces/{workspace_id}/llm-key", response_model=CredentialResponse)
async def upsert_default_credential(
    workspace_id: UUID,
    body: CredentialInput,
    user: CurrentUser,
    session: Session,
) -> CredentialResponse:
    await _lock_account(session, user.id)
    await workspace_access(session, workspace_id, user, minimum_role="admin")
    await _owned_workspace(workspace_id, user, session, for_update=True)
    existing_result = await session.exec(
        select(ProviderCredential).where(
            ProviderCredential.workspace_id == workspace_id,
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
    base_url = (
        _base_url(
            body.provider,
            body.base_url,
            existing=credential.base_url if credential else None,
        )
        if body.base_url is not None or credential is None or body.provider != "ollama"
        else credential.base_url
    )
    key = (
        await resolve_credential_secret(session, credential)
        if credential is not None and body.provider == "ollama" and body.api_key is None
        else _credential_key(body.provider, body.api_key)
    )
    valid, message = await _validate(body.provider, key, base_url)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
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
            key_hint=_key_hint(body.provider, key),
            base_url=base_url,
            is_default=True,
            updated_at=now,
        )
        if key:
            await _set_secret(session, credential, key)
    else:
        if body.provider != "ollama" or body.api_key is not None:
            await _set_secret(session, credential, key)
        credential.base_url = base_url
        credential.status = "active"
        credential.is_default = True
        credential.updated_at = now
    session.add(credential)
    # Registering or rotating a key changes credentials only. Model choices are an
    # independent workspace setting, including roles the user has not selected yet.
    await session.commit()
    await session.refresh(credential)
    return _response(credential)


@router.get("/provider-credentials", response_model=list[CredentialResponse])
async def list_account_credentials(user: CurrentUser, session: Session) -> list[CredentialResponse]:
    return [_response(item) for item in await _workspace_credentials(None, user, session)]


@router.post(
    "/provider-credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_account_credential(
    body: CredentialInput, user: CurrentUser, session: Session
) -> CredentialResponse:
    return await add_credential(None, body, user, session)


@router.put("/provider-credentials/{credential_id}", response_model=CredentialResponse)
async def rotate_account_credential(
    credential_id: UUID, body: CredentialRotation, user: CurrentUser, session: Session
) -> CredentialResponse:
    return await rotate_credential(None, credential_id, body, user, session)


@router.put("/provider-credentials/{credential_id}/default", response_model=CredentialResponse)
async def choose_account_default_credential(
    credential_id: UUID, user: CurrentUser, session: Session
) -> CredentialResponse:
    return await choose_default_credential(None, credential_id, user, session)


@router.delete("/provider-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_account_credential(
    credential_id: UUID, user: CurrentUser, session: Session
) -> None:
    await remove_credential(None, credential_id, user, session)

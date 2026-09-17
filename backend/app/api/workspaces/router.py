from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.credentials import router as credentials_router
from app.api.workspaces.schemas import CreateWorkspaceRequest, SourceResponse, WorkspaceResponse
from app.auth import CurrentUser, bearer
from app.core.config import get_settings
from app.core.credentials import store_credential_secret
from app.core.database import get_session
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source, Workspace

router = APIRouter()
router.include_router(credentials_router)
workspaces = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]


def _response(workspace: Workspace, source_count: int = 0) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        source_count=source_count,
    )


@workspaces.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(user: CurrentUser, session: Session) -> list[WorkspaceResponse]:
    query = (
        select(Workspace, func.count(Source.id))
        .outerjoin(Source, Source.workspace_id == Workspace.id)
        .where(Workspace.owner_id == user.id)
        .group_by(Workspace.id)
        .order_by(Workspace.created_at.desc())
    )
    rows = (await session.exec(query)).all()
    return [_response(workspace, count) for workspace, count in rows]


@workspaces.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: CreateWorkspaceRequest, user: CurrentUser, session: Session
) -> WorkspaceResponse:
    valid, message = await validate_provider_credential(body.llm_provider, body.llm_api_key)
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    workspace = Workspace(owner_id=user.id, name=body.name.strip())
    session.add(workspace)
    credential = ProviderCredential(
        workspace_id=workspace.id,
        owner_id=user.id,
        provider=body.llm_provider,
        key_hint=body.llm_api_key[-4:],
        is_default=True,
    )
    credential.vault_secret_id = await store_credential_secret(
        session,
        secret=body.llm_api_key,
        credential_id=credential.id,
        workspace_id=workspace.id,
        provider=body.llm_provider,
    )
    session.add(credential)
    await session.commit()
    await session.refresh(workspace)
    return _response(workspace)


@workspaces.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> WorkspaceResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    count = await session.exec(
        select(func.count(Source.id)).where(Source.workspace_id == workspace.id)
    )
    return _response(workspace, count.one())


@workspaces.get("/{workspace_id}/sources", response_model=list[SourceResponse])
async def list_sources(workspace_id: UUID, user: CurrentUser, session: Session) -> list[Source]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    result = await session.exec(
        select(Source)
        .where(Source.workspace_id == workspace.id, Source.owner_id == user.id)
        .order_by(Source.created_at.desc())
    )
    return list(result.all())


@workspaces.post("/{workspace_id}/sources/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> dict[str, object]:
    return await _upload_source(workspace_id, file, "document", user, session, credentials)


@workspaces.post("/{workspace_id}/sources/recordings", status_code=status.HTTP_201_CREATED)
async def upload_recording(
    workspace_id: UUID,
    audio: UploadFile,
    user: CurrentUser,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> dict[str, object]:
    return await _upload_source(workspace_id, audio, "meeting", user, session, credentials)


async def _upload_source(
    workspace_id: UUID,
    file: UploadFile,
    kind: str,
    user: CurrentUser,
    session: AsyncSession,
    credentials: HTTPAuthorizationCredentials,
) -> dict[str, object]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    settings = get_settings()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
    filename = file.filename or ("recording.webm" if kind == "meeting" else "document")
    filename = filename.replace("/", "_").replace("\\", "_")
    source = Source(
        workspace_id=workspace.id,
        owner_id=user.id,
        kind=kind,
        title=filename,
        object_path="pending",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
    )
    source.object_path = f"{user.id}/{workspace.id}/{source.id}/{source.title}"
    storage_url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{settings.supabase_storage_bucket}/{quote(source.object_path, safe='/')}"
    )
    headers = {
        "apikey": settings.supabase_publishable_key.get_secret_value(),
        "Authorization": f"Bearer {credentials.credentials}",
        "Content-Type": source.content_type,
        "x-upsert": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(storage_url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Storage unavailable") from exc
    if response.status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Storage upload failed")
    session.add(source)
    await session.commit()
    return {
        "id": str(source.id),
        "sourceId": str(source.id),
        "sourceKind": kind,
        "status": "queued",
        "progress": 0,
        "stage": "uploaded",
    }


router.include_router(workspaces)

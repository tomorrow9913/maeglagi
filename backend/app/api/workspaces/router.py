from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from kombu.exceptions import OperationalError
from pydantic import ValidationError
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces.context import router as context_router
from app.api.workspaces.credentials import router as credentials_router
from app.api.workspaces.directory import active_project
from app.api.workspaces.directory import router as directory_router
from app.api.workspaces.graph import router as graph_router
from app.api.workspaces.review import (
    LiveDraft,
    ReviewUtterance,
    validate_unique_utterances,
)
from app.api.workspaces.review import (
    router as review_router,
)
from app.api.workspaces.schemas import (
    CreateWorkspaceRequest,
    SimilarChunkResponse,
    SourceResponse,
    TranscriptSourceRequest,
    WorkspaceResponse,
)
from app.api.workspaces.source_content import router as source_content_router
from app.auth import CurrentUser, bearer
from app.core.config import get_settings
from app.core.credentials import store_credential_secret
from app.core.database import get_session
from app.modules.context_engine.application.model_catalog import (
    options_for_key,
    with_recommended_defaults,
)
from app.modules.context_engine.application.model_roles import invalid_selections
from app.modules.context_engine.infrastructure.credential_validation import (
    validate_provider_credential,
)
from app.modules.ingestion.application.pipeline import IngestionError, IngestionPipeline
from app.modules.ingestion.application.upload_validation import (
    InvalidUploadError,
    UnsupportedUploadError,
    validate_document,
    validate_recording,
)
from app.modules.ingestion.infrastructure.tasks import process_source
from app.modules.workspaces.domain.source_state import (
    ProcessingStage,
    ReviewState,
    SourceStatus,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source, Workspace

router = APIRouter()
router.include_router(credentials_router)
router.include_router(context_router)
router.include_router(graph_router)
router.include_router(source_content_router)
workspaces = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]


def _job_response(source: Source) -> JobResponse:
    return JobResponse(
        id=source.id,
        source_id=source.id,
        source_kind=source.kind,
        transcript_source=source.transcript_source,
        status=source.status,
        progress=source.progress,
        stage=source.processing_stage,
        error_message=source.error_message,
    )


def _response(workspace: Workspace, source_count: int = 0) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        source_count=source_count,
    )


async def _enqueue_source(source: Source, session: AsyncSession) -> None:
    try:
        process_source.apply_async(args=[str(source.id)], task_id=str(source.id))
    except (OperationalError, ConnectionError) as exc:
        source.status = SourceStatus.FAILED
        source.error_message = "Processing queue unavailable"
        session.add(source)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Processing queue unavailable",
        ) from exc


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
    options = await options_for_key(body.llm_provider, body.llm_api_key)
    problems = invalid_selections(body.models or {}, options)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))
    workspace = Workspace(
        owner_id=user.id,
        name=body.name.strip(),
        # What the user chose wins; whatever they left out gets the key's recommended model.
        model_settings=with_recommended_defaults(
            {role: choice.model_dump() for role, choice in (body.models or {}).items()}, options
        ),
    )
    session.add(workspace)
    # Persist the referenced row before inserting its credential, while keeping
    # both writes in the same transaction.
    await session.flush()
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


@workspaces.post(
    "/{workspace_id}/sources/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
async def upload_document(
    workspace_id: UUID,
    file: UploadFile,
    user: CurrentUser,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> JobResponse:
    source, _ = await _upload_source(workspace_id, file, "document", user, session, credentials)
    source.status = SourceStatus.QUEUED
    source.processing_stage = ProcessingStage.UPLOADED
    await session.commit()
    await _enqueue_source(source, session)
    return _job_response(source)


@workspaces.post(
    "/{workspace_id}/sources/recordings",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
async def upload_recording(
    workspace_id: UUID,
    audio: UploadFile,
    user: CurrentUser,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    live_draft: Annotated[str | None, Form(alias="liveDraft")] = None,
    project_id: Annotated[UUID | None, Form(alias="projectId")] = None,
) -> JobResponse:
    await active_project(session, project_id, workspace_id, user.id)
    draft = None
    if live_draft is not None:
        try:
            draft = LiveDraft.model_validate_json(live_draft)
            validate_unique_utterances(draft.utterances)
        except ValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid live draft") from exc
    source, _ = await _upload_source(workspace_id, audio, "meeting", user, session, credentials)
    source.transcript_source = "server"
    source.review_state = ReviewState.TRANSCRIBING
    source.project_id = project_id
    source.review_utterances = (
        [item.model_dump(by_alias=True, mode="json") for item in draft.utterances] if draft else []
    )
    source.status = SourceStatus.QUEUED
    source.processing_stage = ProcessingStage.UPLOADED
    source.progress = 0
    await session.commit()
    await _enqueue_source(source, session)
    return _job_response(source)


@workspaces.post(
    "/{workspace_id}/sources/transcripts",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
async def create_transcript_source(
    workspace_id: UUID,
    body: TranscriptSourceRequest,
    user: CurrentUser,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> JobResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    await active_project(session, body.project_id, workspace_id, user.id)
    text_value = body.text.strip()
    if not text_value:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transcript text is required")
    now = datetime.now(UTC)
    title = (
        body.title.strip()
        if body.title and body.title.strip()
        else now.strftime("회의 대본 %Y-%m-%d %H:%M")
    )
    content = text_value.encode()
    try:
        utterances = (
            [ReviewUtterance.model_validate(item) for item in body.utterances]
            if body.utterances is not None
            else [ReviewUtterance(id="initial", speakerName="화자 1", text=text_value)]
        )
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid transcript draft"
        ) from exc
    validate_unique_utterances(utterances)
    source = Source(
        workspace_id=workspace.id,
        owner_id=user.id,
        kind="meeting",
        title=title,
        object_path="pending",
        content_type="text/plain; charset=utf-8",
        size_bytes=len(content),
        transcript_source="browser",
        project_id=body.project_id,
        duration_seconds=body.duration_seconds,
        transcript_text=text_value,
        review_utterances=[item.model_dump(by_alias=True, mode="json") for item in utterances],
        review_state=ReviewState.AWAITING_REVIEW,
        status=SourceStatus.AWAITING_REVIEW,
        processing_stage=ProcessingStage.AWAITING_REVIEW,
        progress=0.45,
    )
    source.object_path = f"{user.id}/{workspace.id}/{source.id}/transcript.txt"
    await _upload_object(source, content, credentials)
    session.add(source)
    await session.commit()
    return _job_response(source)


@workspaces.get("/{workspace_id}/search", response_model=list[SimilarChunkResponse])
async def search_workspace(
    workspace_id: UUID,
    q: str,
    user: CurrentUser,
    session: Session,
    limit: int = 10,
) -> list[SimilarChunkResponse]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    if not q.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Search query is required")
    try:
        rows = await IngestionPipeline().search(
            session,
            workspace_id=workspace_id,
            owner_id=user.id,
            query=q.strip(),
            limit=max(1, min(limit, 50)),
        )
    except IngestionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [
        SimilarChunkResponse(
            id=chunk.id,
            source_id=chunk.source_id,
            position=chunk.position,
            content=chunk.content,
            distance=distance,
            start_seconds=chunk.start_seconds,
            end_seconds=chunk.end_seconds,
        )
        for chunk, distance in rows
    ]


async def _upload_source(
    workspace_id: UUID,
    file: UploadFile,
    kind: str,
    user: CurrentUser,
    session: AsyncSession,
    credentials: HTTPAuthorizationCredentials,
) -> tuple[Source, bytes]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
    filename = file.filename or ("recording.webm" if kind == "meeting" else "document")
    filename = filename.replace("/", "_").replace("\\", "_")
    try:
        if kind == "document":
            validate_document(filename, file.content_type, content)
        else:
            extension = validate_recording(filename, file.content_type, content)
            # The browser client names every MediaRecorder blob recording.webm, even on
            # Safari where the bytes and MIME are MP4. Keep the STT filename truthful.
            if filename.lower().endswith(".webm") and extension == ".mp4":
                filename = filename[:-5] + ".mp4"
    except UnsupportedUploadError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except InvalidUploadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
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
    await _upload_object(source, content, credentials)
    session.add(source)
    return source, content


async def _upload_object(
    source: Source, content: bytes, credentials: HTTPAuthorizationCredentials
) -> None:
    settings = get_settings()
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


workspaces.include_router(directory_router)
workspaces.include_router(review_router)
router.include_router(workspaces)

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from kombu.exceptions import OperationalError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces.associations import PersonAssociation, replace_projects
from app.api.workspaces.associations import (
    router as associations_router,
)
from app.api.workspaces.collaboration import router as collaboration_router
from app.api.workspaces.context import router as context_router
from app.api.workspaces.credentials import _credential_key
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
from app.api.workspaces.source_events import router as source_events_router
from app.auth import CurrentUser, bearer
from app.core.config import Settings, get_settings
from app.core.credentials import (
    CredentialUnavailableError,
    resolve_credential_secret,
    store_credential_secret,
)
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
from app.modules.ingestion.infrastructure.pg_executor import enqueue_source as enqueue_pg_source
from app.modules.ingestion.infrastructure.pg_executor import wake_executors
from app.modules.ingestion.infrastructure.tasks import process_source
from app.modules.workspaces.application.access import claim_pending_memberships, workspace_access
from app.modules.workspaces.application.audit import add_audit_event
from app.modules.workspaces.domain.source_state import (
    ProcessingStage,
    ReviewState,
    SourceStatus,
)
from app.modules.workspaces.infrastructure.models import (
    ProviderCredential,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspaceMember,
)

router = APIRouter()
router.include_router(credentials_router)
router.include_router(context_router)
router.include_router(graph_router)
router.include_router(source_content_router)
router.include_router(collaboration_router)
workspaces = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]


def _selected_projects(project_id: UUID | None, project_ids: list[UUID] | None) -> list[UUID]:
    ids = project_ids if project_ids is not None else ([project_id] if project_id else [])
    if len(ids) != len(set(ids)) or (project_id is not None and (not ids or ids[0] != project_id)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid project selection")
    return ids


def _job_response(source: Source) -> JobResponse:
    return JobResponse(
        id=source.id,
        source_id=source.id,
        source_kind=source.kind,
        transcript_source=source.transcript_source,
        status=source.status,
        analysis_mode=source.analysis_mode,
        progress=source.progress,
        stage=source.processing_stage,
        error_message=source.error_message,
    )


def _response(
    workspace: Workspace, source_count: int = 0, role: str = "owner"
) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        source_count=source_count,
        role=role,
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


async def _persist_and_enqueue_source(
    source: Source, session: AsyncSession, settings: Settings | None = None
) -> None:
    if (settings or get_settings()).processing_executor == "postgres":
        await enqueue_pg_source(session, source)
        await session.commit()
        wake_executors()
    else:
        await session.commit()
        await _enqueue_source(source, session)


@workspaces.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(user: CurrentUser, session: Session) -> list[WorkspaceResponse]:
    await claim_pending_memberships(session, user)
    query = (
        select(Workspace, WorkspaceMember.role, func.count(Source.id))
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .outerjoin(Source, Source.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .group_by(Workspace.id, WorkspaceMember.role)
        .order_by(Workspace.created_at.desc())
    )
    rows = (await session.exec(query)).all()
    return [_response(workspace, count, role) for workspace, role, count in rows]


@workspaces.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: CreateWorkspaceRequest, user: CurrentUser, session: Session
) -> WorkspaceResponse:
    from app.api.workspaces.credentials import _base_url, _key_hint, _lock_account

    if body.credential_id is None and body.llm_provider is None:
        if body.llm_api_key is not None or body.llm_base_url is not None or body.models:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Choose a provider before configuring its credential or models",
            )
        from app.modules.agent_workflows.service import AgentWorkflowService

        created = await AgentWorkflowService(session).create_workspace(
            owner_id=user.id, name=body.name
        )
        member = (
            await session.exec(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == created.id,
                    WorkspaceMember.user_id == user.id,
                )
            )
        ).one()
        member.email = user.email or ""
        member.email_normalized = (user.email or "").strip().casefold()
        session.add(member)
        add_audit_event(
            session,
            workspace_id=created.id,
            actor=user,
            action="workspace.created",
            target_type="workspace",
            target_id=created.id,
        )
        await session.commit()
        return WorkspaceResponse(
            id=created.id, name=created.name, created_at=created.created_at, source_count=0
        )

    await _lock_account(session, user.id)
    account_credentials = list(
        (
            await session.exec(
                select(ProviderCredential).where(
                    ProviderCredential.owner_id == user.id,
                    ProviderCredential.workspace_id.is_(None),
                )
            )
        ).all()
    )
    if body.credential_id is not None:
        credential = next(
            (
                item
                for item in account_credentials
                if item.id == body.credential_id and item.status == "active"
            ),
            None,
        )
        if credential is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
        if body.llm_provider is not None and body.llm_provider != credential.provider:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provider mismatch")
        if body.llm_api_key is not None or body.llm_base_url is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use the saved credential")
        try:
            key = await resolve_credential_secret(session, credential)
        except CredentialUnavailableError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Saved credential is unavailable"
            ) from exc
        provider = credential.provider
        base_url = credential.base_url
    else:
        if body.llm_provider is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "credentialId or llmProvider is required"
            )
        provider = body.llm_provider
        key = _credential_key(provider, body.llm_api_key)
        base_url = _base_url(provider, body.llm_base_url)
        credential = None
    valid, message = await (
        validate_provider_credential(provider, key, base_url)
        if provider == "ollama"
        else validate_provider_credential(provider, key)
    )
    if not valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)
    options = await (
        options_for_key(provider, key, base_url, credential.id if credential else None)
        if provider == "ollama"
        else options_for_key(provider, key, credential_id=credential.id)
        if credential is not None
        else options_for_key(provider, key)
    )
    problems = invalid_selections(body.models or {}, options)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))
    workspace = Workspace(owner_id=user.id, name=body.name.strip())
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            email=user.email or "",
            email_normalized=(user.email or "").strip().casefold(),
            role="owner",
            invited_by=user.id,
            joined_at=datetime.now(UTC),
        )
    )
    if credential is None:
        existing_labels = {item.label for item in account_credentials if item.provider == provider}
        label = "기본"
        suffix = 2
        while label in existing_labels:
            label = f"기본 {suffix}"
            suffix += 1
        credential = ProviderCredential(
            workspace_id=None,
            owner_id=user.id,
            provider=provider,
            label=label,
            key_hint=_key_hint(provider, key),
            base_url=base_url,
            is_default=not any(item.is_default for item in account_credentials),
        )
        if key:
            credential.vault_secret_id = await store_credential_secret(
                session,
                secret=key,
                credential_id=credential.id,
                workspace_id=None,
                provider=provider,
            )
        session.add(credential)
    # Every new workspace model choice names the credential used to preview it.
    choices = with_recommended_defaults(
        {
            role: choice.model_dump(mode="json", by_alias=True)
            for role, choice in (body.models or {}).items()
        },
        options,
    )
    workspace.model_settings = {
        role: {**choice, "credentialId": str(credential.id)} for role, choice in choices.items()
    }
    session.add(workspace)
    add_audit_event(
        session,
        workspace_id=workspace.id,
        actor=user,
        action="workspace.created",
        target_type="workspace",
        target_id=workspace.id,
        details={"modelsConfigured": sorted(workspace.model_settings)},
    )
    await session.commit()
    await session.refresh(workspace)
    return _response(workspace)


@workspaces.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> WorkspaceResponse:
    workspace = await session.get(Workspace, workspace_id)
    access = await workspace_access(session, workspace_id, user)
    workspace = access.workspace
    count = await session.exec(
        select(func.count(Source.id)).where(Source.workspace_id == workspace.id)
    )
    return _response(workspace, count.one(), access.member.role)


@workspaces.get("/{workspace_id}/sources", response_model=list[SourceResponse])
async def list_sources(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> list[SourceResponse]:
    access = await workspace_access(session, workspace_id, user)
    workspace = access.workspace
    result = await session.exec(
        select(Source)
        .where(Source.workspace_id == workspace.id, Source.owner_id == workspace.owner_id)
        .order_by(Source.created_at.desc())
    )
    sources = list(result.all())
    if not sources:
        return []
    source_ids = [source.id for source in sources]
    project_rows = (
        await session.exec(
            select(SourceProject)
            .where(
                SourceProject.workspace_id == workspace_id,
                SourceProject.source_id.in_(source_ids),  # type: ignore[attr-defined]
            )
            .order_by(SourceProject.position)
        )
    ).all()
    projects_by_source: dict[UUID, list[UUID]] = {}
    for row in project_rows:
        projects_by_source.setdefault(row.source_id, []).append(row.project_id)
    person_rows = (
        await session.exec(
            select(SourcePerson).where(
                SourcePerson.workspace_id == workspace_id,
                SourcePerson.source_id.in_(source_ids),  # type: ignore[attr-defined]
            )
        )
    ).all()
    people_by_source: dict[UUID, list[dict[str, str]]] = {}
    for row in person_rows:
        people_by_source.setdefault(row.source_id, []).append(
            PersonAssociation(person_id=row.person_id, role=row.role).model_dump(
                by_alias=True, mode="json"
            )
        )
    return [
        SourceResponse.model_validate(source, from_attributes=True).model_copy(
            update={
                "project_ids": projects_by_source.get(source.id)
                or ([source.project_id] if source.project_id else []),
                "associations": people_by_source.get(source.id, []),
                "has_recording": source.kind == "meeting"
                and source.content_type.startswith(("audio/", "video/")),
            }
        )
        for source in sources
    ]


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
    request: Request = None,
) -> JobResponse:
    source, _ = await _upload_source(workspace_id, file, "document", user, session, credentials)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="source.created",
        target_type="source",
        target_id=source.id,
        details={"kind": "document"},
    )
    source.status = SourceStatus.QUEUED
    source.processing_stage = ProcessingStage.UPLOADED
    await _persist_and_enqueue_source(
        source, session, request.app.state.settings if request is not None else None
    )
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
    request: Request = None,
    live_draft: Annotated[str | None, Form(alias="liveDraft")] = None,
    project_id: Annotated[UUID | None, Form(alias="projectId")] = None,
    project_ids: Annotated[str | None, Form(alias="projectIds")] = None,
) -> JobResponse:
    try:
        ids = _selected_projects(
            project_id,
            TypeAdapter(list[UUID]).validate_python(json.loads(project_ids))
            if project_ids is not None
            else None,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid projectIds") from exc
    access = await workspace_access(session, workspace_id, user, minimum_role="editor")
    for identifier in ids:
        await active_project(session, identifier, workspace_id, access.data_owner_id)
    draft = None
    if live_draft is not None:
        try:
            draft = LiveDraft.model_validate_json(live_draft)
            validate_unique_utterances(draft.utterances)
        except ValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid live draft") from exc
    source, _ = await _upload_source(workspace_id, audio, "meeting", user, session, credentials)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="source.created",
        target_type="source",
        target_id=source.id,
        details={"kind": "meeting"},
    )
    source.transcript_source = "server"
    source.review_state = ReviewState.TRANSCRIBING
    source.project_id = ids[0] if ids else None
    source.review_utterances = (
        [item.model_dump(by_alias=True, mode="json") for item in draft.utterances] if draft else []
    )
    source.status = SourceStatus.QUEUED
    source.processing_stage = ProcessingStage.UPLOADED
    source.progress = 0
    await session.flush()
    await replace_projects(session, source, ids)
    await _persist_and_enqueue_source(
        source, session, request.app.state.settings if request is not None else None
    )
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
    access = await workspace_access(session, workspace_id, user, minimum_role="editor")
    workspace = access.workspace
    ids = _selected_projects(body.project_id, body.project_ids)
    for identifier in ids:
        await active_project(session, identifier, workspace_id, access.data_owner_id)
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
        owner_id=access.data_owner_id,
        kind="meeting",
        title=title,
        object_path="pending",
        content_type="text/plain; charset=utf-8",
        size_bytes=len(content),
        transcript_source="browser",
        project_id=ids[0] if ids else None,
        duration_seconds=body.duration_seconds,
        transcript_text=text_value,
        review_utterances=[item.model_dump(by_alias=True, mode="json") for item in utterances],
        review_state=ReviewState.AWAITING_REVIEW,
        status=SourceStatus.AWAITING_REVIEW,
        processing_stage=ProcessingStage.AWAITING_REVIEW,
        progress=0.45,
    )
    source.object_path = f"{access.data_owner_id}/{workspace.id}/{source.id}/transcript.txt"
    await _upload_object(source, content, credentials)
    session.add(source)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="source.created",
        target_type="source",
        target_id=source.id,
        details={"kind": "meeting", "transcriptSource": "browser"},
    )
    await session.flush()
    await replace_projects(session, source, ids)
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
    access = await workspace_access(session, workspace_id, user, minimum_role="viewer")
    if not q.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Search query is required")
    try:
        rows = await IngestionPipeline().search(
            session,
            workspace_id=workspace_id,
            owner_id=access.data_owner_id,
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
    from app.modules.ingestion.application.source_upload import (
        SourceUploadService,
        UploadServiceError,
    )

    settings = get_settings()
    access = await workspace_access(session, workspace_id, user, minimum_role="editor")
    content = await file.read(settings.max_upload_bytes + 1)

    async def writer(source: Source, data: bytes) -> None:
        await _upload_object(source, data, credentials)

    try:
        source = await SourceUploadService(session, settings).upload(
            owner_id=access.data_owner_id,
            workspace_id=workspace_id,
            filename=file.filename,
            content_type=file.content_type,
            content=content,
            kind=kind,
            write_object=writer,
        )
    except UploadServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return source, content


async def _upload_object(
    source: Source, content: bytes, credentials: HTTPAuthorizationCredentials
) -> None:
    from app.modules.ingestion.application.source_upload import (
        UploadServiceError,
        store_source_bytes,
    )

    try:
        settings = get_settings()
        # Shared-workspace uploads write below the workspace owner's storage prefix.
        # The API has already authorized the member, so use the server credential to
        # avoid applying the caller's user-scoped Storage RLS to another owner's path.
        storage_token = (
            settings.supabase_service_role_key.get_secret_value() or credentials.credentials
        )
        await store_source_bytes(source, content, settings=settings, storage_token=storage_token)
    except UploadServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


workspaces.include_router(directory_router)
workspaces.include_router(review_router)
workspaces.include_router(source_events_router)
workspaces.include_router(associations_router)
router.include_router(workspaces)

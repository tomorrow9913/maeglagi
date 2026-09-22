"""Binary upload adapter for MCP clients; shares validation/storage with web uploads."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import bearer
from app.auth.mcp import authenticate_mcp_token
from app.core.database import get_session
from app.mcp.workflow_hints import next_step
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.repositories import WorkflowRepository
from app.modules.ingestion.application.source_upload import (
    SourceUploadService,
    UploadServiceError,
    store_source_bytes,
)
from app.modules.workspaces.application.audit import add_audit_event
from app.modules.workspaces.infrastructure.models import Source

router = APIRouter(prefix="/agent-uploads", tags=["agent-media"])


@router.post("/workspaces/{workspace_id}", status_code=201)
async def upload_agent_media(
    workspace_id: UUID,
    request: Request,
    file: UploadFile,
    kind: Annotated[Literal["document", "meeting"], Form()],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    settings = request.app.state.settings
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "MCP token is required")
    user = await authenticate_mcp_token(credentials.credentials, settings)
    try:
        workspace = await WorkflowRepository(session).workspace(
            user.id, workspace_id, minimum_role="editor"
        )
    except WorkflowError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    content = await file.read(settings.max_upload_bytes + 1)

    async def writer(source: Source, data: bytes) -> None:
        await store_source_bytes(
            source,
            data,
            settings=settings,
            storage_token=settings.supabase_service_role_key.get_secret_value(),
        )

    try:
        source = await SourceUploadService(session, settings).upload(
            owner_id=workspace.owner_id,
            workspace_id=workspace_id,
            filename=file.filename,
            content_type=file.content_type,
            content=content,
            kind=kind,
            write_object=writer,
        )
    except UploadServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    source.analysis_mode = "agent"
    source.status = "awaiting_agent"
    source.processing_stage = "awaiting_agent"
    source.review_state = "awaiting_review" if kind == "meeting" else None
    source.transcript_source = "agent" if kind == "meeting" else None
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="source.created",
        target_type="source",
        target_id=source.id,
        origin="mcp",
        details={"kind": kind},
    )
    session.add(source)
    await session.commit()
    return {
        "sourceId": str(source.id),
        "workspaceId": str(source.workspace_id),
        "title": source.title,
        "kind": source.kind,
        "status": source.status,
        "analysisMode": "agent",
        "nextAction": next_step(workspace_id, source.id, kind=kind, has_media=True),
    }

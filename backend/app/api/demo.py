"""Public, read-only access to the single explicitly published demo workspace.

This router never changes authentication on private routes. The deployment selects
the public dataset; callers cannot select an owner or another workspace.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces import context, directory, graph, source_content
from app.api.workspaces.router import get_workspace, list_sources
from app.api.workspaces.schemas import (
    ContextItemResponse,
    ContextStoreResponse,
    KnowledgeGraphResponse,
    SourceResponse,
    WorkspaceResponse,
)
from app.auth import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.modules.workspaces.infrastructure.models import Source, Workspace

router = APIRouter(prefix="/demo", tags=["public-demo"])
Session = Annotated[AsyncSession, Depends(get_session)]


async def published_workspace(
    session: Session, settings: Annotated[Settings, Depends(get_settings)]
) -> Workspace:
    try:
        workspace_id = UUID(settings.demo_workspace_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "Public demo is not configured") from exc
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(503, "Public demo is not available")
    return workspace


Published = Annotated[Workspace, Depends(published_workspace)]


def reader(workspace: Workspace) -> AuthUser:
    # Used only for the fixed, explicitly public workspace's read handlers.
    return AuthUser(id=workspace.owner_id)


async def published_source(source_id: UUID, workspace: Published, session: Session) -> Source:
    source = await session.get(Source, source_id)
    if (
        source is None
        or source.workspace_id != workspace.id
        or source.owner_id != workspace.owner_id
    ):
        raise HTTPException(404, "Source not found")
    return source


@router.get("/workspace", response_model=WorkspaceResponse)
async def workspace_info(workspace: Published, session: Session):
    return await get_workspace(workspace.id, reader(workspace), session)


@router.get("/sources", response_model=list[SourceResponse])
async def sources(workspace: Published, session: Session):
    return await list_sources(workspace.id, reader(workspace), session)


@router.get("/people", response_model=list[directory.PersonResponse])
async def people(workspace: Published, session: Session):
    return await directory.list_people(workspace.id, reader(workspace), session)


@router.get("/projects", response_model=list[directory.ProjectResponse])
async def projects(workspace: Published, session: Session):
    return await directory.list_projects(workspace.id, reader(workspace), session)


@router.get("/sources/{source_id}/content", response_model=source_content.SourceContentResponse)
async def content(
    source: Annotated[Source, Depends(published_source)], workspace: Published, session: Session
):
    return await source_content.get_source_content(source.id, reader(workspace), session)


@router.get("/sources/{source_id}/playback-url", response_model=source_content.PlaybackUrlResponse)
async def playback(
    source: Annotated[Source, Depends(published_source)], workspace: Published, session: Session
):
    return await source_content.recording_playback_url(source.id, reader(workspace), session)


@router.get("/sources/{source_id}/export.md")
async def markdown(
    source: Annotated[Source, Depends(published_source)], workspace: Published, session: Session
):
    return await source_content.export_meeting_markdown(source.id, reader(workspace), session)


@router.get("/context", response_model=list[ContextItemResponse])
@router.get("/timeline", response_model=list[ContextItemResponse])
async def timeline(
    workspace: Published,
    session: Session,
    kind: Annotated[list[str] | None, Query()] = None,
    source_kind: Annotated[list[str] | None, Query()] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
):
    return await context.list_context_items(
        workspace.id, reader(workspace), session, kind, source_kind, from_, to
    )


@router.get("/context-store", response_model=ContextStoreResponse | None)
async def current_context(workspace: Published, session: Session):
    return await context.get_context_store(workspace.id, reader(workspace), session)


@router.get("/graph", response_model=KnowledgeGraphResponse)
async def knowledge_graph(
    workspace: Published,
    session: Session,
    store: graph.GraphStore,
    at: datetime | None = None,
    include_materials: bool = Query(default=True, alias="includeMaterials"),
):
    return await graph.get_knowledge_graph(
        workspace.id,
        reader(workspace),
        session,
        store,
        at=at,
        include_materials=include_materials,
    )

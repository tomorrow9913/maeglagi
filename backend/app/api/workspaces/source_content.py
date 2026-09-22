from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.review import ReviewUtterance
from app.auth import CurrentUser
from app.core.config import get_settings
from app.core.database import get_session
from app.modules.agent_workflows.repositories import WorkflowRepository
from app.modules.workspaces.application.access import workspace_access
from app.modules.workspaces.application.media_access import MediaAccessError, signed_media_url
from app.modules.workspaces.domain.source_state import ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import Source

router = APIRouter(prefix="/sources")
Session = Annotated[AsyncSession, Depends(get_session)]


class SourceChunkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    text: str
    # Meeting chunks only: where in the recording this text was said, in seconds.
    start_seconds: float | None = Field(default=None, serialization_alias="startSeconds")
    end_seconds: float | None = Field(default=None, serialization_alias="endSeconds")


class SourceContentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: UUID = Field(serialization_alias="sourceId")
    title: str
    kind: str
    has_recording: bool = Field(serialization_alias="hasRecording")
    original_text: str | None = Field(default=None, serialization_alias="originalText")
    utterances: list[ReviewUtterance] = Field(default_factory=list)
    chunks: list[SourceChunkResponse]


def has_recording(source: Source) -> bool:
    return (
        source.kind == "meeting"
        and source.size_bytes > 0
        and bool(source.object_path)
        and source.content_type.startswith(("audio/", "video/"))
    )


class PlaybackUrlResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    url: str
    expires_at: datetime = Field(serialization_alias="expiresAt")


async def _owned_source(source_id: UUID, user: CurrentUser, session: AsyncSession) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if source.owner_id == user.id:
        return source
    access = await workspace_access(session, source.workspace_id, user)
    if source.owner_id != access.data_owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return source


@router.post("/{source_id}/playback-url", response_model=PlaybackUrlResponse)
async def recording_playback_url(
    source_id: UUID, user: CurrentUser, session: Session
) -> PlaybackUrlResponse:
    source = await _owned_source(source_id, user, session)
    if not has_recording(source):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    try:
        signed = await signed_media_url(source, get_settings())
    except MediaAccessError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return PlaybackUrlResponse(url=signed.url, expires_at=signed.expires_at)


@router.get("/{source_id}/export.md")
async def export_meeting_markdown(source_id: UUID, user: CurrentUser, session: Session) -> Response:
    source = await _owned_source(source_id, user, session)
    if source.kind != "meeting":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found")
    if source.review_state != ReviewState.CONFIRMED and source.status != SourceStatus.SUCCEEDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting is not confirmed")
    lines = [f"# {source.title}", ""]
    snapshot = source.confirmed_snapshot or {}
    projects = snapshot.get("projects") or (
        [snapshot["project"]] if snapshot.get("project") else []
    )
    if projects:
        lines.extend(["Projects: " + ", ".join(item["name"] for item in projects), ""])
    for item in source.review_utterances:
        if not str(item.get("text", "")).strip():
            continue
        seconds = item.get("startSeconds")
        timestamp = (
            f"[{int(seconds // 60):02d}:{int(seconds % 60):02d}] "
            if isinstance(seconds, (int, float))
            else ""
        )
        lines.extend(
            [f"{timestamp}**{item.get('speakerName', 'Speaker')}**", "", str(item["text"]), ""]
        )
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="meeting-{source.id}.md"'},
    )


@router.get("/{source_id}/content", response_model=SourceContentResponse)
async def get_source_content(
    source_id: UUID, user: CurrentUser, session: Session
) -> SourceContentResponse:
    """The persisted source text and indexed evidence chunks in reading order.

    Chunk ids are the ones evidence points at (timeline, graph, answers), so the viewer can
    scroll to the exact passage. A source that has not been indexed yet has no chunks.
    """
    source = await _owned_source(source_id, user, session)
    content = await WorkflowRepository(session).source_content_for_source(source)
    return SourceContentResponse(
        source_id=source.id,
        title=source.title,
        kind=source.kind,
        has_recording=has_recording(source),
        original_text=content.text,
        utterances=[
            ReviewUtterance.model_validate(item.model_dump(by_alias=True))
            for item in content.utterances
        ],
        chunks=[
            SourceChunkResponse(
                id=chunk.id,
                text=chunk.text,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
            )
            for chunk in content.chunks
        ],
    )

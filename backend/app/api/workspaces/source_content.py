from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.review import ReviewUtterance
from app.auth import CurrentUser
from app.core.config import get_settings
from app.core.database import get_session
from app.modules.context_engine.infrastructure.models import Chunk
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
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return source


@router.post("/{source_id}/playback-url", response_model=PlaybackUrlResponse)
async def recording_playback_url(
    source_id: UUID, user: CurrentUser, session: Session
) -> PlaybackUrlResponse:
    source = await _owned_source(source_id, user, session)
    if not has_recording(source):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    settings = get_settings()
    key = settings.supabase_service_role_key.get_secret_value()
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Playback unavailable")
    path = quote(source.object_path, safe="/")
    bucket = quote(settings.supabase_storage_bucket, safe="")
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/sign/{bucket}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            result = await client.post(
                url,
                json={"expiresIn": 300},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
        result.raise_for_status()
        signed = result.json().get("signedURL") or result.json().get("signedUrl")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Playback unavailable") from exc
    if not isinstance(signed, str) or not signed.startswith(f"/object/sign/{bucket}/{path}?"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Invalid playback URL")
    return PlaybackUrlResponse(
        url=f"{settings.supabase_url.rstrip('/')}/storage/v1{signed}",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


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
    utterances = [ReviewUtterance.model_validate(item) for item in source.review_utterances]
    edited_text = "\n\n".join(
        f"{item.speaker_name}: {item.text}" for item in utterances if item.text
    )
    original_text = edited_text or (
        source.transcript_text or source.raw_transcript_text
        if source.kind == "meeting"
        else source.content_text
    )
    found = await session.exec(
        select(Chunk)
        .where(Chunk.source_id == source.id, Chunk.owner_id == user.id)
        .order_by(Chunk.position)
    )
    return SourceContentResponse(
        source_id=source.id,
        title=source.title,
        kind=source.kind,
        has_recording=has_recording(source),
        original_text=original_text,
        utterances=utterances,
        chunks=[
            SourceChunkResponse(
                id=chunk.id,
                text=chunk.content,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
            )
            for chunk in found.all()
        ],
    )

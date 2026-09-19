from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.context_engine.infrastructure.models import Chunk
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
    chunks: list[SourceChunkResponse]


@router.get("/{source_id}/content", response_model=SourceContentResponse)
async def get_source_content(
    source_id: UUID, user: CurrentUser, session: Session
) -> SourceContentResponse:
    """The normalized text of a source, chunk by chunk, in reading order.

    Chunk ids are the ones evidence points at (timeline, graph, answers), so the viewer can
    scroll to the exact passage. A source that has not been indexed yet has no chunks.
    """
    source = await session.get(Source, source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    found = await session.exec(
        select(Chunk)
        .where(Chunk.source_id == source.id, Chunk.owner_id == user.id)
        .order_by(Chunk.position)
    )
    return SourceContentResponse(
        source_id=source.id,
        title=source.title,
        kind=source.kind,
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

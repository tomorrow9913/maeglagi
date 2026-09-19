"""Authenticated, bounded source job updates over server-sent events."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.auth import CurrentUser
from app.core.database import session_factory
from app.modules.workspaces.infrastructure.models import Source, Workspace

router = APIRouter(prefix="/{workspace_id}/source-events")

MAX_SOURCES = 100
POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0
STREAM_SECONDS = 55.0


def _parse_source_ids(value: str) -> list[UUID]:
    if not value or len(value) > 4000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid source_ids")
    parts = value.split(",")
    if len(parts) > MAX_SOURCES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Too many source_ids")
    try:
        ids = [UUID(part.strip()) for part in parts]
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid source_ids") from exc
    if len(set(ids)) != len(ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate source_ids")
    return ids


async def _load_jobs(
    session: AsyncSession, workspace_id: UUID, owner_id: UUID, source_ids: list[UUID]
) -> dict[UUID, str]:
    rows = await session.exec(
        select(
            Source.id,
            Source.kind,
            Source.transcript_source,
            Source.status,
            Source.analysis_mode,
            Source.progress,
            Source.processing_stage,
            Source.error_message,
        ).where(
            Source.id.in_(source_ids),  # type: ignore[attr-defined]
            Source.workspace_id == workspace_id,
            Source.owner_id == owner_id,
        )
    )
    return {
        source_id: JobResponse(
            id=source_id,
            source_id=source_id,
            source_kind=kind,
            transcript_source=transcript_source,
            status=source_status,
            analysis_mode=analysis_mode,
            progress=progress,
            stage=stage,
            error_message=error_message,
        ).model_dump_json(by_alias=True)
        for (
            source_id,
            kind,
            transcript_source,
            source_status,
            analysis_mode,
            progress,
            stage,
            error_message,
        ) in rows
    }


async def _read_jobs(workspace_id: UUID, owner_id: UUID, source_ids: list[UUID]) -> dict[UUID, str]:
    # Each poll owns one short session and closes it before the next sleep.
    async with session_factory() as session:
        return await _load_jobs(session, workspace_id, owner_id, source_ids)


def _job_event(payload: str) -> str:
    return f"event: job\ndata: {payload}\n\n"


async def _stream_events(
    request: Request,
    workspace_id: UUID,
    owner_id: UUID,
    source_ids: list[UUID],
    initial: dict[UUID, str],
    *,
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    stream_seconds: float = STREAM_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    seen = initial.copy()
    if await request.is_disconnected():
        return
    for source_id in source_ids:
        yield _job_event(initial[source_id])

    started = now()
    deadline = started + stream_seconds
    next_poll = started + poll_seconds
    next_heartbeat = started + heartbeat_seconds
    while now() < deadline:
        if await request.is_disconnected():
            return
        delay = min(next_poll, next_heartbeat, deadline) - now()
        if delay > 0:
            await sleep(delay)
        if await request.is_disconnected():
            return
        current = now()
        if current >= deadline:
            return
        if current >= next_poll:
            try:
                latest = await asyncio.wait_for(
                    _read_jobs(workspace_id, owner_id, source_ids),
                    timeout=min(5.0, deadline - current),
                )
            except (TimeoutError, DBAPIError):
                # End the stream so the authenticated client can reconnect.
                return
            if now() >= deadline:
                return
            for source_id in source_ids:
                payload = latest.get(source_id)
                if payload is not None and payload != seen.get(source_id):
                    seen[source_id] = payload
                    yield _job_event(payload)
            next_poll = current + poll_seconds
        if current >= next_heartbeat:
            yield ": heartbeat\n\n"
            next_heartbeat = current + heartbeat_seconds


@router.get("")
async def source_events(
    workspace_id: UUID, source_ids: str, request: Request, user: CurrentUser
) -> StreamingResponse:
    ids = _parse_source_ids(source_ids)
    async with session_factory() as session:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None or workspace.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
        initial = await _load_jobs(session, workspace_id, user.id, ids)
        if len(initial) != len(ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return StreamingResponse(
        _stream_events(request, workspace_id, user.id, ids, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

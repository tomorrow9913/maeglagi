"""Authenticated, bounded source job updates over server-sent events."""

import asyncio
import time
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces.source_event_broker import SourceEventBroker, SourceSubscription
from app.auth import CurrentUser
from app.core.database import session_scope
from app.modules.workspaces.application.access import workspace_access
from app.modules.workspaces.infrastructure.models import Source

router = APIRouter(prefix="/{workspace_id}/source-events")

MAX_SOURCES = 100
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
    # A notification owns one short session; no database session is held by an idle stream.
    async with session_scope() as session:
        return await _load_jobs(session, workspace_id, owner_id, source_ids)


def _job_event(payload: str) -> str:
    return f"event: job\ndata: {payload}\n\n"


async def _stream_events(
    request: Request,
    workspace_id: UUID,
    owner_id: UUID,
    source_ids: list[UUID],
    initial: dict[UUID, str],
    subscription: SourceSubscription,
    broker: SourceEventBroker,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    stream_seconds: float = STREAM_SECONDS,
) -> AsyncIterator[str]:
    seen = initial.copy()
    deadline = time.monotonic() + stream_seconds
    try:
        if await request.is_disconnected():
            return
        for source_id in source_ids:
            yield _job_event(initial[source_id])
        while (remaining := deadline - time.monotonic()) > 0:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(
                    subscription.queue.get(), timeout=min(heartbeat_seconds, remaining)
                )
            except TimeoutError:
                if time.monotonic() < deadline:
                    yield ": heartbeat\n\n"
                continue
            if event is None or await request.is_disconnected():
                return
            try:
                latest = await asyncio.wait_for(
                    _read_jobs(workspace_id, owner_id, [event.source_id]), timeout=5.0
                )
            except (TimeoutError, DBAPIError):
                # The client reconnects for a fresh, authenticated snapshot.
                return
            payload = latest.get(event.source_id)
            if payload is None:
                return
            if payload != seen.get(event.source_id):
                seen[event.source_id] = payload
                yield _job_event(payload)
    finally:
        broker.unsubscribe(subscription)


@router.get("")
async def source_events(
    workspace_id: UUID, source_ids: str, request: Request, user: CurrentUser
) -> StreamingResponse:
    ids = _parse_source_ids(source_ids)
    broker: SourceEventBroker | None = getattr(request.app.state, "source_event_broker", None)
    if broker is None or not broker.healthy:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Source event listener unavailable"
        )
    subscription = None
    async with session_scope() as session:
        try:
            access = await workspace_access(session, workspace_id, user)
            data_owner_id = access.data_owner_id
            subscription = broker.subscribe(data_owner_id, workspace_id, ids)
            initial = await _load_jobs(session, workspace_id, data_owner_id, ids)
            if len(initial) != len(ids):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
        except BaseException:
            if subscription is not None:
                broker.unsubscribe(subscription)
            raise
    assert subscription is not None
    return StreamingResponse(
        _stream_events(request, workspace_id, data_owner_id, ids, initial, subscription, broker),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.schemas import (
    ContextItemResponse,
    ContextItemSourceResponse,
    ContextStoreItemResponse,
    ContextStoreResponse,
)
from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.context_engine.application.context_store import state_from_record
from app.modules.context_engine.application.temporal import as_utc
from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord
from app.modules.workspaces.infrastructure.models import Source, Workspace

router = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]


async def _owned_workspace(
    workspace_id: UUID, user: CurrentUser, session: AsyncSession
) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


def _occurred(record: ContextRecord) -> datetime:
    return as_utc(record.occurred_at or record.created_at) or record.created_at


def _superseded_by(records: list[ContextRecord]) -> dict[UUID, UUID]:
    """Map each replaced decision to the latest decision that says it replaces it."""
    replaced: dict[UUID, UUID] = {}
    for newer in sorted(records, key=_occurred):
        target = (newer.metadata_ or {}).get("supersedes")
        if newer.kind != "decision" or not target:
            continue
        for older in records:
            if (
                older.kind == "decision"
                and older.id != newer.id
                and (older.metadata_ or {}).get("key") == target
            ):
                replaced[older.id] = newer.id
    return replaced


@router.get("/{workspace_id}/context", response_model=list[ContextItemResponse])
async def list_context_items(
    workspace_id: UUID,
    user: CurrentUser,
    session: Session,
    kind: Annotated[list[str] | None, Query()] = None,
    source_kind: Annotated[list[str] | None, Query()] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> list[ContextItemResponse]:
    """The workspace timeline: decisions, issues, tasks and events, newest first."""
    workspace = await _owned_workspace(workspace_id, user, session)
    found = await session.exec(
        select(ContextRecord, Source)
        .join(Source, Source.id == ContextRecord.source_id)  # type: ignore[arg-type]
        .where(ContextRecord.workspace_id == workspace.id, ContextRecord.owner_id == user.id)
    )
    rows = list(found.all())
    replaced_by = _superseded_by([record for record, _ in rows])

    start, end = as_utc(from_), as_utc(to)
    items: list[ContextItemResponse] = []
    for record, source in sorted(rows, key=lambda row: _occurred(row[0]), reverse=True):
        moment = _occurred(record)
        if kind and record.kind not in kind:
            continue
        if source_kind and source.kind not in source_kind:
            continue
        if (start and moment < start) or (end and moment > end):
            continue
        items.append(
            ContextItemResponse(
                id=record.id,
                kind=record.kind,
                title=record.title,
                summary=record.body,
                occurred_at=moment,
                sources=[
                    ContextItemSourceResponse(
                        id=source.id, kind=source.kind, title=source.title, chunk_id=record.chunk_id
                    )
                ],
                superseded_by=replaced_by.get(record.id),
            )
        )
    return items


@router.get("/{workspace_id}/context-store", response_model=ContextStoreResponse | None)
async def get_context_store(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> ContextStoreResponse | None:
    """The project's current situation, or null until the first source has been analyzed."""
    workspace = await _owned_workspace(workspace_id, user, session)
    found = await session.exec(
        select(ContextStoreRecord).where(
            ContextStoreRecord.workspace_id == workspace.id,
            ContextStoreRecord.owner_id == user.id,
        )
    )
    record = found.first()
    if record is None:
        return None
    state = state_from_record(record)
    return ContextStoreResponse(
        subject=state.subject,
        summary=state.summary,
        current_state=state.current_state,
        open_issues=[ContextStoreItemResponse(**i.model_dump()) for i in state.open_issues],
        decisions=[ContextStoreItemResponse(**d.model_dump()) for d in state.decisions],
        next_actions=[ContextStoreItemResponse(**a.model_dump()) for a in state.next_actions],
        source_ids=state.source_ids,
        updated_at=record.updated_at,
    )

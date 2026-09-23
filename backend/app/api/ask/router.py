import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.modules.context_engine.application.context_store import state_from_record
from app.modules.context_engine.application.model_roles import ModelRole
from app.modules.context_engine.domain.context_store import ContextStoreState
from app.modules.context_engine.infrastructure.models import Chunk, ContextStoreRecord
from app.modules.ingestion.application.pipeline import IngestionError, IngestionPipeline
from app.modules.retrieval.application.answer import answer_events
from app.modules.retrieval.application.hybrid import HybridRetriever
from app.modules.retrieval.application.lexical import search_lexically
from app.modules.retrieval.domain.answer import error_event
from app.modules.retrieval.infrastructure.graph_neighborhood import GraphNeighborhood
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.application.access import workspace_access
from app.modules.workspaces.application.audit import add_audit_event
from app.modules.workspaces.infrastructure.models import Source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]

INTERNAL_ERROR = "답변을 만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."


class AskRequest(BaseModel):
    question: str = Field(max_length=2000)
    history: list["AskHistoryTurn"] = Field(default_factory=list, max_length=6)
    credential_id: UUID | None = Field(default=None, alias="credentialId")

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("질문을 입력해 주세요.")
        return value


class AskHistoryTurn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=4000)


async def _sse(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """Server-sent events the frontend's `apiStream` reads: `data: {json}` lines, then [DONE]."""
    try:
        async for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except Exception:  # the stream is already open, so a failure can only be reported in it
        logger.exception("ask stream failed")
        yield f"data: {json.dumps(error_event(INTERNAL_ERROR), ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _load_sources(
    session: AsyncSession, workspace_id: UUID, owner_id: UUID, ids: list[UUID]
) -> dict[UUID, Source]:
    found = await session.exec(
        select(Source).where(
            Source.id.in_(ids),  # type: ignore[attr-defined]
            Source.workspace_id == workspace_id,
            Source.owner_id == owner_id,
        )
    )
    return {source.id: source for source in found.all()}


async def _load_store(
    session: AsyncSession, workspace_id: UUID, owner_id: UUID
) -> ContextStoreState | None:
    found = await session.exec(
        select(ContextStoreRecord).where(
            ContextStoreRecord.workspace_id == workspace_id,
            ContextStoreRecord.owner_id == owner_id,
        )
    )
    record = found.first()
    return state_from_record(record) if record else None


@router.post("/{workspace_id}/ask")
async def ask(
    workspace_id: UUID,
    body: AskRequest,
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
) -> StreamingResponse:
    """Answer a question from the workspace's own sources, streaming, with its evidence.

    Everything that touches the database or the graph (key lookup, search, evidence) is finished
    before the first byte is sent; only the model's tokens stream. No evidence means no model call.
    """
    access = await workspace_access(session, workspace_id, user, minimum_role="viewer")
    data_owner_id = access.data_owner_id

    ingestion = IngestionPipeline(settings)
    try:
        provider = await ingestion.provider_with_model(
            session,
            workspace_id=workspace_id,
            owner_id=user.id,
            role=ModelRole.ANSWER,
            credential_id=body.credential_id,
        )
    except IngestionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    async def embed(question: str) -> list[float]:
        return await ingestion.embed_query(
            session, workspace_id=workspace_id, owner_id=user.id, query=question
        )

    async def search(
        embedding: list[float], source_ids: list[UUID] | None, limit: int
    ) -> list[tuple[Chunk, float]]:
        return await ingestion.search_by_embedding(
            session,
            workspace_id=workspace_id,
            owner_id=data_owner_id,
            embedding=embedding,
            limit=limit,
            source_ids=source_ids,
        )

    async def load_sources(ids: list[UUID]) -> dict[UUID, Source]:
        return await _load_sources(session, workspace_id, data_owner_id, ids)

    async def lexical(question: str, source_ids: list[UUID] | None, limit: int):
        return await search_lexically(
            session,
            workspace_id=workspace_id,
            owner_id=data_owner_id,
            question=question,
            source_ids=source_ids,
            limit=limit,
        )

    graph_store = Neo4jGraphStore.from_settings(settings) if settings.neo4j_enabled else None
    try:
        retriever = HybridRetriever(
            embed=embed,
            search=search,
            load_sources=load_sources,
            lexical_search=lexical,
            graph=GraphNeighborhood(graph_store) if graph_store else None,
        )
        # A short follow-up can depend on the subject of the preceding question.
        retrieval_query = (
            f"{body.question} {body.history[-1].question}"
            if body.history and len(body.question) < 80
            else body.question
        )
        retrieval = await retriever.retrieve(workspace_id, retrieval_query)
    except IngestionError as exc:  # e.g. no key that can embed the question
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    finally:
        if graph_store is not None:
            await graph_store.close()

    store = await _load_store(session, workspace_id, data_owner_id)
    add_audit_event(
        session,
        workspace_id=workspace_id,
        actor=user,
        action="ask.asked",
        target_type="workspace",
        target_id=workspace_id,
        details={
            "questionLength": len(body.question),
            "historyTurns": len(body.history),
            "provider": provider.adapter.id,
            "model": provider.model,
            "credentialScope": provider.credential_scope,
            "credentialId": str(provider.credential_id) if provider.credential_id else None,
            "generationMethod": "service_model",
            "provenanceTrust": "verified_runtime",
        },
    )
    if hasattr(session, "commit"):
        await session.commit()
    events = answer_events(
        adapter=provider.adapter,
        api_key=provider.api_key,
        model=provider.model,
        question=body.question,
        history=[(item.question, item.answer) for item in body.history],
        retrieval=retrieval,
        store=store,
    )
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

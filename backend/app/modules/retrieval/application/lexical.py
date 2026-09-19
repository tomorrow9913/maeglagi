"""Bounded keyword evidence for workspaces without usable vector search."""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, case, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import Source

MAX_TOKENS = 8
MAX_TEXT = 1200
MAX_RESULTS = 8
STOP_WORDS = {"최근", "어떤", "무엇", "뭐가", "왜", "어떻게", "있나요", "알려줘", "해줘"}


@dataclass(frozen=True)
class LexicalMatch:
    source_id: UUID
    chunk_id: UUID | None
    kind: str
    title: str
    text: str
    timestamp: float | None = None


def query_terms(question: str) -> list[str]:
    """Use words and Hangul pairs so inflected Korean questions still find their stems."""
    terms: list[str] = []
    for word in re.findall(r"[a-z0-9]+|[가-힣]+", question.lower()):
        if len(word) < 2 or word in STOP_WORDS:
            continue
        candidates = [word]
        if re.fullmatch(r"[가-힣]+", word) and len(word) > 2:
            candidates.extend(word[i : i + 2] for i in range(len(word) - 1))
        for term in candidates:
            if term not in terms:
                terms.append(term)
            if len(terms) >= MAX_TOKENS:
                return terms
    return terms


def _predicate_and_rank(column: object, terms: list[str]) -> tuple[object, object]:
    matches = [func.lower(column).contains(term, autoescape=True) for term in terms]
    return or_(*matches), sum((case((match, 1), else_=0) for match in matches), 0)


async def search_lexically(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    owner_id: UUID,
    question: str,
    limit: int = MAX_RESULTS,
    source_ids: list[UUID] | None = None,
) -> list[LexicalMatch]:
    """Return approved, owner-scoped evidence; SQL caps rows and transferred text."""
    terms = query_terms(question)
    if not terms or limit <= 0 or source_ids == []:
        return []
    limit = min(limit, MAX_RESULTS)
    scope = (
        Source.workspace_id == workspace_id,
        Source.owner_id == owner_id,
    )
    eligible_chunks = (
        *scope,
        Source.status == SourceStatus.SUCCEEDED,
        or_(Source.review_state.is_(None), Source.review_state == ReviewState.CONFIRMED),
    )
    if source_ids is not None:
        selected_sources = (Source.id.in_(source_ids),)  # type: ignore[attr-defined]
        eligible_chunks += selected_sources
        scope += selected_sources

    predicate, rank = _predicate_and_rank(Chunk.content, terms)
    statement = (
        select(
            Chunk.id,
            Chunk.source_id,
            Source.kind,
            Source.title,
            func.substr(Chunk.content, 1, MAX_TEXT),
            Chunk.start_seconds,
        )
        .join(Source, Chunk.source_id == Source.id)
        .where(
            *eligible_chunks,
            Chunk.workspace_id == workspace_id,
            Chunk.owner_id == owner_id,
            predicate,
        )
        .order_by(rank.desc(), Chunk.created_at.desc(), Chunk.id)
        .limit(limit)
    )
    rows = (await session.exec(statement)).all()
    matches = [
        LexicalMatch(source_id, chunk_id, kind, title, text, timestamp)
        for chunk_id, source_id, kind, title, text, timestamp in rows
    ]
    if len(matches) >= limit:
        return matches

    # Parsed documents and confirmed meetings remain usable even when indexing failed.
    content = case((Source.kind == "meeting", Source.transcript_text), else_=Source.content_text)
    source_ready = or_(
        and_(
            Source.kind == "meeting",
            Source.review_state == ReviewState.CONFIRMED,
            Source.processing_stage.in_(  # type: ignore[attr-defined]
                (
                    ProcessingStage.CONFIRMED,
                    ProcessingStage.ANALYZING,
                    ProcessingStage.GRAPHING,
                    ProcessingStage.COMPLETED,
                )
            ),
        ),
        and_(
            Source.kind == "document",
            Source.processing_stage.in_(  # type: ignore[attr-defined]
                (
                    ProcessingStage.ANALYZING,
                    ProcessingStage.GRAPHING,
                    ProcessingStage.COMPLETED,
                )
            ),
        ),
    )
    predicate, rank = _predicate_and_rank(content, terms)
    position = case(
        *(
            (
                func.lower(content).contains(term, autoescape=True),
                func.strpos(func.lower(content), term),
            )
            for term in terms
        ),
        else_=1,
    )
    excerpt = func.substr(content, func.greatest(1, position - 100), MAX_TEXT)
    statement = (
        select(Source.id, Source.kind, Source.title, excerpt)
        .where(
            *scope,
            source_ready,
            Source.status != SourceStatus.AWAITING_REVIEW,
            content.is_not(None),
            func.length(func.trim(content)) > 0,
            predicate,
        )
        .order_by(rank.desc(), Source.created_at.desc(), Source.id)
        .limit(limit - len(matches))
    )
    represented = {match.source_id for match in matches}
    if represented:
        statement = statement.where(Source.id.not_in(represented))  # type: ignore[attr-defined]
    matches.extend(
        LexicalMatch(source_id, None, kind, title, text)
        for source_id, kind, title, text in (await session.exec(statement)).all()
    )
    return matches

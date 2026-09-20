"""Bounded keyword evidence for workspaces without usable vector search."""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Float, and_, case, cast, func, or_, true
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
    words = [
        word
        for word in re.findall(r"[a-z0-9]+|[가-힣]+", question.lower())
        if len(word) >= 2 and word not in STOP_WORDS
    ]
    terms: list[str] = []
    pairs = (
        word[i : i + 2]
        for word in words
        if re.fullmatch(r"[가-힣]+", word) and len(word) > 2
        for i in range(len(word) - 1)
    )
    for candidates in (words, pairs):
        for term in candidates:
            if term not in terms:
                terms.append(term)
            if len(terms) >= MAX_TOKENS:
                return terms
    return terms


def _bm25(corpus: object, terms: list[str]) -> tuple[object, object, object]:
    """Rank character n-gram matches with corpus-wide BM25 (k1=1.2, b=0.75)."""
    text = corpus.c.text
    document_length = cast(corpus.c.doc_len, Float)
    predicates = [text.contains(term, autoescape=True) for term in terms]
    statistics = (
        select(
            func.count().label("document_count"),
            func.avg(corpus.c.doc_len).label("average_length"),
            *(
                func.sum(case((match, 1), else_=0)).label(f"document_frequency_{index}")
                for index, match in enumerate(predicates)
            ),
        )
        .select_from(corpus)
        .cte("bm25_statistics")
    )
    scores = []
    for index, term in enumerate(terms):
        frequency = cast(
            (func.length(text) - func.length(func.replace(text, term, ""))) / len(term), Float
        )
        document_frequency = getattr(statistics.c, f"document_frequency_{index}")
        inverse_frequency = func.ln(
            1.0
            + (statistics.c.document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        normalized_frequency = (frequency * 2.2) / (
            frequency
            + 1.2 * (0.25 + 0.75 * document_length / func.nullif(statistics.c.average_length, 0))
        )
        scores.append(inverse_frequency * normalized_frequency)
    return or_(*predicates), sum(scores, 0), statistics


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

    chunk_corpus = (
        select(
            Chunk.id.label("id"),
            func.lower(Chunk.content).label("text"),
            func.length(Chunk.content).label("doc_len"),
        )
        .join(Source, Chunk.source_id == Source.id)
        .where(
            *eligible_chunks,
            Chunk.workspace_id == workspace_id,
            Chunk.owner_id == owner_id,
        )
        .cte("chunk_corpus")
    )
    predicate, rank, statistics = _bm25(chunk_corpus, terms)
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
        .join(chunk_corpus, chunk_corpus.c.id == Chunk.id)
        .join(statistics, true())
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
    source_corpus = (
        select(
            Source.id.label("id"),
            func.lower(content).label("text"),
            func.length(content).label("doc_len"),
        )
        .where(
            *scope,
            source_ready,
            Source.status != SourceStatus.AWAITING_REVIEW,
            content.is_not(None),
            func.length(func.trim(content)) > 0,
        )
        .cte("source_corpus")
    )
    predicate, rank, statistics = _bm25(source_corpus, terms)
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
        .join(source_corpus, source_corpus.c.id == Source.id)
        .join(statistics, true())
        .where(
            *scope,
            source_ready,
            Source.status != SourceStatus.AWAITING_REVIEW,
            content.is_not(None),
            func.length(func.trim(content)) > 0,
            predicate,
        )
        .order_by(rank.desc(), Source.created_at.desc(), Source.id)
        .limit(max(limit - len(matches), min(limit, 2)))
    )
    represented = {match.source_id for match in matches}
    if represented:
        statement = statement.where(Source.id.not_in(represented))  # type: ignore[attr-defined]
    source_matches = [
        LexicalMatch(source_id, None, kind, title, text)
        for source_id, kind, title, text in (await session.exec(statement)).all()
    ]
    # Keep room for parsed sources even when indexed chunks fill the result window.
    return matches[: limit - len(source_matches)] + source_matches

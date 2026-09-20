import os
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import literal, select, text, true, union_all
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.modules.context_engine.application.model_catalog import has_indexed_chunks
from app.modules.ingestion.application.pipeline import IngestionPipeline
from app.modules.retrieval.application.hybrid import HybridRetriever
from app.modules.retrieval.application.lexical import (
    MAX_RESULTS,
    MAX_TEXT,
    _bm25,
    query_terms,
    search_lexically,
)


async def test_postgres_bm25_prefers_shorter_equally_relevant_passage() -> None:
    url = os.environ.get("ASK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set ASK_TEST_DATABASE_URL to a local PostgreSQL test database")
    engine = create_async_engine(url)
    corpus = union_all(
        select(
            literal(1).label("id"),
            literal("redis cache").label("text"),
            literal(11).label("doc_len"),
        ),
        select(literal(2), literal("redis " + "filler " * 100), literal(706)),
        select(literal(3), literal("unrelated note"), literal(14)),
    ).cte("corpus")
    predicate, score, statistics = _bm25(corpus, ["redis"])
    statement = (
        select(corpus.c.id, score.label("score"))
        .join(statistics, true())
        .where(predicate)
        .order_by(score.desc())
    )
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
            assert [row.id for row in rows] == [1, 2]
            assert rows[0].score > rows[1].score > 0
    finally:
        await engine.dispose()


class Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self.rows


class Session:
    def __init__(self, chunk_rows: list[tuple[Any, ...]], source_rows: list[tuple[Any, ...]]):
        self.chunk_rows = chunk_rows
        self.source_rows = source_rows
        self.statements: list[Any] = []

    async def exec(self, statement: Any) -> Rows:
        self.statements.append(statement)
        return Rows(self.chunk_rows if "JOIN sources" in str(statement) else self.source_rows)


async def test_text_only_chunks_do_not_lock_embedding_model() -> None:
    url = os.environ.get("ASK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set ASK_TEST_DATABASE_URL to a local pgvector test database")
    engine = create_async_engine(url)
    workspace, other = uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "CREATE TEMP TABLE chunks (id uuid PRIMARY KEY, workspace_id uuid, "
                    "embedding vector(2))"
                )
            )
            await connection.execute(
                text("INSERT INTO chunks VALUES (:id, :workspace, NULL)"),
                {"id": uuid4(), "workspace": workspace},
            )
            await connection.execute(
                text("INSERT INTO chunks VALUES (:id, :workspace, '[0.1,0.2]'::vector)"),
                {"id": uuid4(), "workspace": other},
            )
            async with AsyncSession(connection) as session:
                assert not await has_indexed_chunks(session, workspace)
                await connection.execute(
                    text("INSERT INTO chunks VALUES (:id, :workspace, '[0.1,0.2]'::vector)"),
                    {"id": uuid4(), "workspace": workspace},
                )
                assert await has_indexed_chunks(session, workspace)
    finally:
        await engine.dispose()


def test_korean_pairs_and_mixed_language_terms() -> None:
    assert "결정" in query_terms("최근 어떤 결정이 바뀌었어?")
    assert "redis" in query_terms("Redis를 왜 도입했나요?")
    assert query_terms("? !") == []
    terms = query_terms("마에글라기에서는 Redis를 왜 도입했나요?")
    assert terms[:3] == ["마에글라기에서는", "redis", "도입했나요"]
    assert len(terms) == 8


async def test_parsed_source_is_retained_when_eight_chunks_match() -> None:
    owner, workspace, source = (uuid4() for _ in range(3))
    chunks = [
        (uuid4(), uuid4(), "document", "오래된 문서", "Redis 이전 결정", None) for _ in range(8)
    ]
    session = Session(chunks, [(source, "meeting", "새 회의", "Redis 도입")])

    matches = await search_lexically(  # type: ignore[arg-type]
        session, workspace_id=workspace, owner_id=owner, question="Redis", limit=8
    )

    assert len(matches) == 8
    assert sum(match.chunk_id is not None for match in matches) == 7
    assert matches[-1].source_id == source and matches[-1].chunk_id is None


async def test_source_only_matches_fill_the_result_window_without_chunks() -> None:
    owner, workspace = uuid4(), uuid4()
    sources = [(uuid4(), "document", f"문서 {index}", "Redis 결정") for index in range(8)]
    session = Session([], sources)

    matches = await search_lexically(  # type: ignore[arg-type]
        session, workspace_id=workspace, owner_id=owner, question="Redis", limit=8
    )

    assert len(matches) == 8
    assert [match.source_id for match in matches] == [source[0] for source in sources]
    assert all(match.chunk_id is None for match in matches)


async def test_null_embedding_chunk_is_returned_from_bounded_eligible_query() -> None:
    owner, workspace, source, chunk = (uuid4() for _ in range(4))
    session = Session([(chunk, source, "meeting", "회의", "결정 내용", 42.0)], [])

    matches = await search_lexically(  # type: ignore[arg-type]
        session,
        workspace_id=workspace,
        owner_id=owner,
        question="최근 어떤 결정이 바뀌었어?",
        limit=100,
    )

    assert matches[0].chunk_id == chunk and matches[0].timestamp == 42.0
    statement = session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "JOIN sources" in sql and "chunks.embedding" not in sql
    assert "sources.status" in sql and "sources.review_state" in sql
    assert "sources.owner_id" in sql and "chunks.owner_id" in sql
    assert "sources.workspace_id" in sql and "chunks.workspace_id" in sql
    assert "WITH chunk_corpus AS" in sql
    assert "ln(" in sql and "replace(" in sql and "avg(" in sql
    assert "SELECT count(*)" in sql
    assert 1 in compiled.params.values()  # substring starts at first character
    assert MAX_TEXT in compiled.params.values() and MAX_RESULTS in compiled.params.values()


async def test_postgres_null_vectors_and_confirmed_source_text() -> None:
    url = os.environ.get("ASK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set ASK_TEST_DATABASE_URL to an isolated pgvector test database")
    engine = create_async_engine(url)
    owner, other, workspace = uuid4(), uuid4(), uuid4()
    chunk_source, meeting, document, draft, upload, foreign = (uuid4() for _ in range(6))
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("""
                CREATE TEMP TABLE sources (
                    id uuid PRIMARY KEY, workspace_id uuid, owner_id uuid, kind text,
                    title text, status text, review_state text, processing_stage text,
                    transcript_text text, content_text text,
                    created_at timestamptz DEFAULT now()
                )
            """)
            )
            await connection.execute(
                text("""
                CREATE TEMP TABLE chunks (
                    id uuid PRIMARY KEY, source_id uuid, workspace_id uuid, owner_id uuid,
                    position integer, content text, start_seconds float, end_seconds float,
                    embedding vector(1536), created_at timestamptz DEFAULT now()
                )
            """)
            )
            rows = [
                (
                    chunk_source,
                    owner,
                    "document",
                    "succeeded",
                    None,
                    "completed",
                    None,
                    "Redis 캐시 결정 token",
                ),
                (
                    meeting,
                    owner,
                    "meeting",
                    "failed",
                    "confirmed",
                    "analyzing",
                    "token 승인된 회의",
                    None,
                ),
                (
                    document,
                    owner,
                    "document",
                    "failed",
                    None,
                    "analyzing",
                    None,
                    "token 파싱된 문서",
                ),
                (
                    draft,
                    owner,
                    "meeting",
                    "awaiting_review",
                    "awaiting_review",
                    "awaiting_review",
                    "token 미확인 초안",
                    None,
                ),
                (
                    upload,
                    owner,
                    "document",
                    "queued",
                    None,
                    "uploaded",
                    None,
                    "token 미파싱 업로드",
                ),
                (
                    foreign,
                    other,
                    "document",
                    "failed",
                    None,
                    "analyzing",
                    None,
                    "token 다른 소유자",
                ),
            ]
            for identifier, owner_id, kind, status, review, stage, transcript, content in rows:
                await connection.execute(
                    text("""
                    INSERT INTO sources (id, workspace_id, owner_id, kind, title, status,
                                         review_state, processing_stage, transcript_text,
                                         content_text)
                    VALUES (:id, :workspace, :owner, :kind, 'QA', :status, :review,
                            :stage, :transcript, :content)
                """),
                    dict(
                        id=identifier,
                        workspace=workspace,
                        owner=owner_id,
                        kind=kind,
                        status=status,
                        review=review,
                        stage=stage,
                        transcript=transcript,
                        content=content,
                    ),
                )
            await connection.execute(
                text("""
                INSERT INTO chunks (id, source_id, workspace_id, owner_id, position, content)
                    VALUES (:id, :source, :workspace, :owner, 0, 'Redis 캐시 결정 token')
            """),
                dict(id=uuid4(), source=chunk_source, workspace=workspace, owner=owner),
            )

            session = AsyncSession(bind=connection)
            pipeline = IngestionPipeline(Settings(_env_file=None))
            vector = [0.1] * 1536

            async def embed(question: str) -> list[float]:
                return vector

            async def search(
                embedding: list[float], source_ids: list[Any] | None, limit: int
            ) -> list[Any]:
                return await pipeline.search_by_embedding(
                    session,
                    workspace_id=workspace,
                    owner_id=owner,
                    embedding=embedding,
                    source_ids=source_ids,
                    limit=limit,
                )

            async def lexical(question: str, source_ids: list[Any] | None, limit: int) -> list[Any]:
                return await search_lexically(
                    session,
                    workspace_id=workspace,
                    owner_id=owner,
                    question=question,
                    source_ids=source_ids,
                    limit=limit,
                )

            async def load_sources(ids: list[Any]) -> dict[Any, Any]:
                return {}

            assert await search(vector, None, 6) == []
            retrieval = await HybridRetriever(
                embed=embed,
                search=search,
                lexical_search=lexical,
                load_sources=load_sources,
            ).retrieve(workspace, "Redis를 왜 도입했나요?")
            assert [e.source.source_id for e in retrieval.evidence] == [chunk_source]
            confirmed = await lexical("token 승인", [meeting, draft, foreign], 8)
            parsed = await lexical("token 문서", [document, upload, foreign], 8)
            assert [(m.source_id, m.chunk_id) for m in confirmed] == [(meeting, None)]
            assert [(m.source_id, m.chunk_id) for m in parsed] == [(document, None)]
            mixed = await lexical("token", None, 8)
            assert len(mixed) == 3
            assert mixed[0].source_id == chunk_source
            assert {m.source_id for m in mixed[1:]} == {meeting, document}
            assert mixed[0].chunk_id is not None
            assert all(m.chunk_id is None for m in mixed[1:])
            await session.close()
    finally:
        await engine.dispose()


async def test_processed_source_text_has_source_only_citation_and_scoped_excerpt() -> None:
    owner, workspace, source = (uuid4() for _ in range(3))
    session = Session([], [(source, "document", "결정문", "결정이 변경됐다")])

    matches = await search_lexically(  # type: ignore[arg-type]
        session,
        workspace_id=workspace,
        owner_id=owner,
        question="결정은?",
        source_ids=[source],
    )

    assert matches[0].chunk_id is None and matches[0].text == "결정이 변경됐다"
    statement = session.statements[1]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "sources.id IN" in sql and "greatest" in sql and "strpos" in sql
    assert "sources.status" in sql and "sources.review_state" in sql
    assert "sources.processing_stage" in sql and "sources.kind" in sql
    assert "WITH source_corpus AS" in sql and "ln(" in sql


async def test_no_terms_or_no_allowed_sources_do_not_query() -> None:
    session = Session([], [])
    assert (
        await search_lexically(  # type: ignore[arg-type]
            session, workspace_id=uuid4(), owner_id=uuid4(), question="?"
        )
        == []
    )
    assert (
        await search_lexically(  # type: ignore[arg-type]
            session, workspace_id=uuid4(), owner_id=uuid4(), question="결정", source_ids=[]
        )
        == []
    )
    assert session.statements == []


async def test_sql_failure_is_not_converted_to_no_evidence() -> None:
    class Broken:
        async def exec(self, statement: Any) -> Any:
            raise RuntimeError("database failed")

    with pytest.raises(RuntimeError, match="database failed"):
        await search_lexically(  # type: ignore[arg-type]
            Broken(), workspace_id=uuid4(), owner_id=uuid4(), question="결정"
        )

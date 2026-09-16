from datetime import UTC, datetime
from uuid import uuid4

from app.modules.context_engine.infrastructure.models import Chunk, ContextRecord
from app.modules.retrieval.domain.models import GraphEntity, GraphEvidence, GraphRelation


def test_chunk_and_context_preserve_evidence_chain() -> None:
    workspace_id = uuid4()
    source_id = uuid4()
    chunk = Chunk(
        workspace_id=workspace_id,
        source_id=source_id,
        owner_id=uuid4(),
        position=0,
        content="근거 문장",
        start_seconds=12.5,
        end_seconds=18.0,
    )
    context = ContextRecord(
        workspace_id=workspace_id,
        source_id=source_id,
        chunk_id=chunk.id,
        owner_id=chunk.owner_id,
        kind="decision",
        title="출시일 확정",
        body="9월 20일에 출시한다.",
        occurred_at=datetime(2026, 9, 16, tzinfo=UTC),
    )

    assert context.source_id == chunk.source_id
    assert context.chunk_id == chunk.id
    assert context.occurred_at is not None


def test_graph_models_store_references_without_raw_source_content() -> None:
    evidence = GraphEvidence(source_id=uuid4(), chunk_id=uuid4(), timestamp=datetime.now(UTC))
    source = GraphEntity(
        id=uuid4(), workspace_id=uuid4(), kind="person", name="담당자", evidence=evidence
    )
    target = GraphEntity(
        id=uuid4(),
        workspace_id=source.workspace_id,
        kind="project",
        name="맥락이",
        evidence=evidence,
    )
    relation = GraphRelation(
        id=uuid4(),
        workspace_id=source.workspace_id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        kind="OWNS",
        evidence=evidence,
    )

    assert {"content", "body", "text"}.isdisjoint(GraphEntity.model_fields)
    assert {"content", "body", "text"}.isdisjoint(GraphRelation.model_fields)
    assert relation.evidence.source_id == evidence.source_id
    assert relation.evidence.chunk_id == evidence.chunk_id

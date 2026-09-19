"""Notion TSK-50/53 contracts with deterministic provider responses, not live AI validation."""

from uuid import uuid4

from app.modules.context_engine.application.context_store import (
    ContextStoreService,
    ContextStoreUpdater,
)
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.ingestion.application.source_analysis import analyze_source
from tests.seeds import SEEDS
from tests.test_entity_resolution import FakeStore
from tests.test_extraction_pipeline import FakeAdapter
from tests.test_source_analysis import FakeRepository


async def test_four_demo_sources_update_one_store_and_keep_each_timeline():
    workspace, owner = uuid4(), uuid4()
    repository = FakeRepository()
    source_ids = []
    graph = FakeStore()
    for seed in SEEDS:
        source = uuid4()
        source_ids.append(str(source))
        adapter = FakeAdapter(seed.responses)
        pipeline = ExtractionPipeline(adapter, "test-key", model="fixture")
        warnings = await analyze_source(
            adapter=adapter,
            api_key="test-key",
            model="fixture",
            context_store=ContextStoreService(repository, ContextStoreUpdater(pipeline)),
            graph_store=graph,
            workspace_id=workspace,
            owner_id=owner,
            source_id=source,
            title=seed.title,
            subject="API 성능 개선",
            text=seed.text,
        )
        assert warnings == []
        assert repository.record is not None
        assert repository.record.workspace_id == workspace
        assert set(repository.record.source_ids) == set(source_ids)
        assert repository.record.current_state
        assert len(repository.timeline) == len(source_ids)
        assert repository.timeline[source]

    record = repository.record
    assert any(item["title"] == "Redis 도입 결정" for item in record.decisions)
    assert any(item["title"] == "캐시 무효화 규칙 초안 작성" for item in record.next_actions)
    assert {
        row["name"]
        for query, params in graph.calls
        if "MERGE (e:Entity {id: row.id})" in query
        for row in params["rows"]
    } >= {
        "박지훈",
        "최서연",
        "Redis",
        "Redis 도입 결정",
    }

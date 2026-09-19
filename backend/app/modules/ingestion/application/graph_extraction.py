import logging
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.context_engine.application.entity_resolution import resolve_extraction
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.ingestion.application.pipeline import IngestionError, IngestionPipeline
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.retrieval.infrastructure.graph_writer import GraphWriter
from app.modules.retrieval.infrastructure.temporal_queries import TemporalQueries
from app.modules.workspaces.infrastructure.models import Source

logger = logging.getLogger(__name__)


async def extract_into_graph(
    *,
    adapter: ProviderAdapter,
    api_key: str,
    store: Neo4jGraphStore,
    model: str,
    workspace_id: UUID,
    source_id: UUID,
    title: str,
    text: str,
) -> list[str]:
    """Extract (5 stages) -> resolve/merge entities -> upsert into Neo4j. Returns warnings."""
    # Only decisions nobody has replaced yet can be replaced, so those are the candidates the
    # Event stage may pick a `supersedes` from.
    current = await TemporalQueries(store).current_decisions(workspace_id)
    result = await ExtractionPipeline(adapter, api_key, model=model).extract(
        text, title=title, known_decisions=[decision.name for decision in current]
    )
    # The upload date says nothing about when the document's facts started, so no fallback
    # start is passed: a relation without a stated start keeps an unknown valid_from.
    graph = resolve_extraction(result, workspace_id=workspace_id, source_id=source_id)
    warnings = [*result.warnings, *graph.warnings]
    warnings += await GraphWriter(store).write(graph)
    return warnings


class GraphExtractionService:
    """Runs graph extraction for a source, skipping it where the workspace cannot support it."""

    def __init__(
        self, ingestion: IngestionPipeline | None = None, settings: Settings | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.ingestion = ingestion or IngestionPipeline(self.settings)

    async def run(self, session: AsyncSession, *, source: Source, text: str) -> list[str]:
        if not self.settings.neo4j_enabled:
            return self._skip(source, "Neo4j가 설정되지 않았습니다.")
        try:
            adapter, api_key = await self.ingestion.provider_for(
                session, source=source, capability="structuredOutput"
            )
        except IngestionError as exc:
            return self._skip(source, str(exc))
        store = Neo4jGraphStore.from_settings(self.settings)
        try:
            warnings = await extract_into_graph(
                adapter=adapter,
                api_key=api_key,
                store=store,
                model=self.settings.extraction_model,
                workspace_id=source.workspace_id,
                source_id=source.id,
                title=source.title,
                text=text,
            )
        finally:
            await store.close()
        for warning in warnings:
            logger.warning("graph extraction (source %s): %s", source.id, warning)
        return warnings

    def _skip(self, source: Source, reason: str) -> list[str]:
        logger.info("graph extraction skipped (source %s): %s", source.id, reason)
        return [f"그래프 추출을 건너뛰었습니다: {reason}"]

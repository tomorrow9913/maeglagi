import logging
from collections.abc import Callable
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.context_engine.application.context_store import (
    ContextStoreRepository,
    ContextStoreService,
    ContextStoreUpdater,
)
from app.modules.context_engine.application.directory_resolution import (
    canonicalize_directory_entities,
)
from app.modules.context_engine.application.entity_resolution import resolve_extraction
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.application.model_roles import ModelRole
from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.context_engine.infrastructure.context_store_repository import (
    SqlContextStoreRepository,
)
from app.modules.ingestion.application.pipeline import IngestionError, IngestionPipeline
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.retrieval.infrastructure.graph_writer import GraphWriter
from app.modules.workspaces.domain.source_state import ReviewState
from app.modules.workspaces.infrastructure.models import Source, Workspace

logger = logging.getLogger(__name__)


async def analyze_source(
    *,
    adapter: ProviderAdapter,
    api_key: str,
    model: str,
    context_store: ContextStoreService,
    graph_store: Neo4jGraphStore | None,
    workspace_id: UUID,
    owner_id: UUID,
    source_id: UUID,
    title: str,
    subject: str,
    text: str,
    directory_snapshot: dict | None = None,
) -> list[str]:
    """One extraction per source, read three ways: timeline, Context Store, graph.

    The Context Store holds the project's *current situation*; the graph holds the *structure* of
    its work. Returns the warnings from every step.
    """
    # Only decisions nobody has replaced can be replaced, so those are the candidates the Event
    # stage may pick a `supersedes` from.
    known = await context_store.current_decisions(workspace_id)
    pipeline = ExtractionPipeline(adapter, api_key, model=model)
    hint = None
    if directory_snapshot:
        project = directory_snapshot.get("project") or {}
        hint = {
            "people": [
                {
                    "name": item.get("name"),
                    "role": item.get("role"),
                    "aliases": item.get("aliases", []),
                }
                for item in directory_snapshot.get("people", [])
            ],
            "project": {
                "name": project.get("name"),
                "goal": project.get("goal"),
                "description": project.get("description"),
                "ownerName": project.get("ownerName"),
                "ownerRole": project.get("ownerRole"),
            },
        }
    result = await pipeline.extract(
        text, title=title, known_decisions=known, directory_context=hint
    )
    trusted_directory_identifiers = canonicalize_directory_entities(
        result, directory_snapshot, text
    )
    warnings = list(result.warnings)

    warnings += await context_store.apply(
        workspace_id=workspace_id,
        owner_id=owner_id,
        source_id=source_id,
        source_title=title,
        subject=subject,
        text=text,
        result=result,
    )

    if graph_store is None:
        warnings.append("Neo4j가 설정되지 않아 그래프 저장을 건너뛰었습니다.")
        return warnings
    # The upload date says nothing about when the document's facts started, so no fallback
    # start is passed: a relation without a stated start keeps an unknown valid_from.
    graph = resolve_extraction(
        result,
        workspace_id=workspace_id,
        source_id=source_id,
        trusted_directory_identifiers=trusted_directory_identifiers,
    )
    warnings += graph.warnings
    warnings += await GraphWriter(graph_store).write(graph)
    return warnings


class SourceAnalysisService:
    """Analyzes a source with the workspace's own key, skipping it where none can do the job."""

    def __init__(
        self,
        ingestion: IngestionPipeline | None = None,
        settings: Settings | None = None,
        repository_factory: Callable[[AsyncSession], ContextStoreRepository] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.ingestion = ingestion or IngestionPipeline(self.settings)
        self.repository_factory = repository_factory or SqlContextStoreRepository

    async def run(self, session: AsyncSession, *, source: Source, text: str) -> list[str]:
        if source.kind == "meeting" and source.review_state in {
            ReviewState.TRANSCRIBING,
            ReviewState.AWAITING_REVIEW,
        }:
            return self._skip(source, "대본 확인이 끝나지 않았습니다.")
        try:
            adapter, api_key, model = await self.ingestion.provider_with_model(
                session,
                workspace_id=source.workspace_id,
                owner_id=source.owner_id,
                role=ModelRole.EXTRACTION,
            )
        except IngestionError as exc:
            return self._skip(source, str(exc))

        workspace = await session.get(Workspace, source.workspace_id)
        pipeline = ExtractionPipeline(adapter, api_key, model=model)
        context_store = ContextStoreService(
            self.repository_factory(session), ContextStoreUpdater(pipeline)
        )
        graph_store = (
            Neo4jGraphStore.from_settings(self.settings) if self.settings.neo4j_enabled else None
        )
        try:
            warnings = await analyze_source(
                adapter=adapter,
                api_key=api_key,
                model=model,
                context_store=context_store,
                graph_store=graph_store,
                workspace_id=source.workspace_id,
                owner_id=source.owner_id,
                source_id=source.id,
                title=source.title,
                subject=workspace.name if workspace else source.title,
                text=text,
                directory_snapshot=source.confirmed_snapshot,
            )
            # Release the Context Store row lock (SELECT ... FOR UPDATE) as soon as we are done.
            await session.commit()
        finally:
            if graph_store is not None:
                await graph_store.close()
        for warning in warnings:
            logger.warning("source analysis (source %s): %s", source.id, warning)
        return warnings

    def _skip(self, source: Source, reason: str) -> list[str]:
        logger.info("source analysis skipped (source %s): %s", source.id, reason)
        return [f"소스 분석을 건너뛰었습니다: {reason}"]

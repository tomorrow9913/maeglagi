import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
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
from app.modules.context_engine.application.entity_resolution import (
    ResolvedGraph,
    resolve_extraction,
)
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.application.model_roles import ModelRole
from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.context_engine.domain.extraction import ExtractionResult
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
    result: ExtractionResult | None = None,
    resolved_graph: ResolvedGraph | None = None,
    context_applied: bool = False,
    context_warnings: list[str] | None = None,
    on_extracted: Callable[[ExtractionResult, ResolvedGraph], Awaitable[None]] | None = None,
    on_context_applied: Callable[[list[str]], Awaitable[None]] | None = None,
) -> list[str]:
    """One extraction per source, read three ways: timeline, Context Store, graph.

    The Context Store holds the project's *current situation*; the graph holds the *structure* of
    its work. Returns the warnings from every step.
    """
    # Only decisions nobody has replaced can be replaced, so those are the candidates the Event
    # stage may pick a `supersedes` from.
    if result is None:
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
    graph = resolved_graph or resolve_extraction(
        result,
        workspace_id=workspace_id,
        source_id=source_id,
        trusted_directory_identifiers=trusted_directory_identifiers,
    )
    if on_extracted is not None and resolved_graph is None:
        await on_extracted(result, graph)
    warnings = [*result.warnings, *(context_warnings or [])]

    if not context_applied:
        applied_warnings = await context_store.apply(
            workspace_id=workspace_id,
            owner_id=owner_id,
            source_id=source_id,
            source_title=title,
            subject=subject,
            text=text,
            result=result,
        )
        warnings += applied_warnings
        if on_context_applied is not None:
            await on_context_applied(applied_warnings)

    if graph_store is None:
        warnings.append("Neo4j가 설정되지 않아 그래프 저장을 건너뛰었습니다.")
        return warnings
    # The upload date says nothing about when the document's facts started, so no fallback
    # start is passed: a relation without a stated start keeps an unknown valid_from.
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
        fingerprint = hashlib.sha256(
            json.dumps(
                [source.title, text, source.review_revision, source.confirmed_snapshot],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        checkpoint = source.analysis_checkpoint
        if checkpoint is not None and checkpoint.get("fingerprint") != fingerprint:
            raise RuntimeError(
                "Source changed after analysis began; explicit replacement is required"
            )
        if checkpoint is not None and checkpoint["phase"] == "done":
            return list(checkpoint.get("warnings", []))
        if checkpoint is not None and checkpoint["phase"] == "context_applied":
            # All SQL writes committed with this phase. Graph replay needs only the
            # stored graph, even if the extraction credential has since disappeared.
            graph = ResolvedGraph.model_validate(checkpoint["graph"])
            result = ExtractionResult.model_validate(checkpoint["result"])
            warnings = [*result.warnings, *checkpoint.get("context_warnings", [])]
            graph_store = (
                Neo4jGraphStore.from_settings(self.settings)
                if self.settings.neo4j_enabled
                else None
            )
            if graph_store is None:
                warnings.append("Neo4j가 설정되지 않아 그래프 저장을 건너뛰었습니다.")
            else:
                try:
                    warnings += graph.warnings
                    warnings += await GraphWriter(graph_store).write(graph)
                finally:
                    await graph_store.close()
            source.analysis_checkpoint = {
                **checkpoint,
                "phase": "done",
                "warnings": warnings,
            }
            session.add(source)
            await session.commit()
            return warnings
        try:
            adapter, api_key, model = await self.ingestion.provider_with_model(
                session,
                workspace_id=source.workspace_id,
                owner_id=source.owner_id,
                role=ModelRole.EXTRACTION,
            )
        except IngestionError as exc:
            if checkpoint is not None:
                raise
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
            async def save_extraction(result: ExtractionResult, graph: ResolvedGraph) -> None:
                source.analysis_checkpoint = {
                    "fingerprint": fingerprint,
                    "phase": "extracted",
                    "result": result.model_dump(mode="json"),
                    "graph": graph.model_dump(mode="json"),
                }
                session.add(source)
                await session.commit()

            async def save_context(applied_warnings: list[str]) -> None:
                # Context rows and this phase transition commit atomically.
                source.analysis_checkpoint = {
                    **source.analysis_checkpoint,
                    "phase": "context_applied",
                    "context_warnings": applied_warnings,
                }
                session.add(source)
                await session.commit()

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
                result=ExtractionResult.model_validate(checkpoint["result"])
                if checkpoint is not None
                else None,
                resolved_graph=ResolvedGraph.model_validate(checkpoint["graph"])
                if checkpoint is not None
                else None,
                context_applied=checkpoint is not None
                and checkpoint["phase"] == "context_applied",
                context_warnings=checkpoint.get("context_warnings")
                if checkpoint is not None
                else None,
                on_extracted=save_extraction,
                on_context_applied=save_context,
            )
            source.analysis_checkpoint = {
                **source.analysis_checkpoint,
                "phase": "done",
                "warnings": warnings,
            }
            session.add(source)
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

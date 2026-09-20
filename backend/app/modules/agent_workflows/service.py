"""Application service shared by HTTP and MCP adapters for keyless agent work."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.modules.agent_workflows.context_updater import KeylessContextUpdater
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.locks import analysis_lock
from app.modules.agent_workflows.repositories import (
    WorkflowRepository,
    source_info,
    workspace_info,
)
from app.modules.agent_workflows.schemas import (
    AgentUtterance,
    AnalysisContext,
    AnalysisSubmission,
    SourceContent,
    SourceInfo,
    WorkspaceInfo,
)
from app.modules.agent_workflows.validation import (
    context_fingerprint,
    result_fingerprint,
    source_fingerprint,
    validate_extraction,
)
from app.modules.context_engine.application.context_store import ContextStoreService
from app.modules.context_engine.application.entity_resolution import ResolvedGraph
from app.modules.context_engine.domain.extraction import (
    ClassificationOutput,
    ContextOutput,
    EntityOutput,
    EventOutput,
    ExtractionResult,
    RelationOutput,
)
from app.modules.context_engine.infrastructure.context_store_repository import (
    SqlContextStoreRepository,
)
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.ingestion.application.chunking import CharacterOverlapChunker
from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.application.source_analysis import analyze_source
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.application.media_access import (
    MediaAccessError,
    SignedMediaUrl,
    signed_media_url,
)
from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import Source, SourceProject, Workspace


def _source_text(source: Source) -> str:
    if source.kind == "meeting":
        if source.review_state != ReviewState.CONFIRMED:
            raise WorkflowError("review_required", "Transcript must be confirmed", 409)
        text = source.transcript_text
    else:
        text = source.content_text
    if not text or not text.strip():
        raise WorkflowError("text_required", "Source text is required", 409)
    return text


class AgentWorkflowService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = WorkflowRepository(session)

    async def list_workspaces(self, *, owner_id: UUID) -> list[WorkspaceInfo]:
        rows = (
            await self.session.exec(
                select(Workspace)
                .where(Workspace.owner_id == owner_id)
                .order_by(Workspace.created_at.desc(), Workspace.id)
            )
        ).all()
        return [workspace_info(row) for row in rows]

    async def create_workspace(self, *, owner_id: UUID, name: str) -> WorkspaceInfo:
        name = name.strip()
        if not name or len(name) > 120:
            raise WorkflowError("invalid_name", "Workspace name is required", 422)
        workspace = Workspace(owner_id=owner_id, name=name, model_settings={})
        self.session.add(workspace)
        await self.session.commit()
        return workspace_info(workspace)

    async def list_sources(self, *, owner_id: UUID, workspace_id: UUID) -> list[SourceInfo]:
        await self.repository.workspace(owner_id, workspace_id)
        rows = (
            await self.session.exec(
                select(Source)
                .where(Source.workspace_id == workspace_id, Source.owner_id == owner_id)
                .order_by(Source.created_at.desc(), Source.id)
            )
        ).all()
        return [source_info(row) for row in rows]

    async def source_content(
        self, *, owner_id: UUID, workspace_id: UUID, source_id: UUID
    ) -> SourceContent:
        return await self.repository.source_content(owner_id, workspace_id, source_id)

    async def media_download_url(
        self, *, owner_id: UUID, workspace_id: UUID, source_id: UUID
    ) -> SignedMediaUrl:
        source = await self.repository.source(owner_id, workspace_id, source_id)
        try:
            return await signed_media_url(source, self.settings)
        except MediaAccessError as exc:
            raise WorkflowError("media_unavailable", str(exc), exc.status_code) from exc

    async def _create_source(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        title: str,
        kind: str,
        object_path: str,
        content_type: str,
        size_bytes: int,
        text: str | None,
        project_ids: list[UUID] | None,
    ) -> SourceInfo:
        await self.repository.workspace(owner_id, workspace_id, lock=True)
        if kind not in {"document", "meeting"}:
            raise WorkflowError("invalid_kind", "Source kind is invalid", 422)
        title = title.strip()
        if not title or len(title) > 255 or size_bytes < 0:
            raise WorkflowError("invalid_source", "Source title or size is invalid", 422)
        ids = list(dict.fromkeys(project_ids or []))
        if ids:
            from app.modules.workspaces.infrastructure.models import WorkspaceProject

            rows = (
                await self.session.exec(
                    select(WorkspaceProject).where(
                        WorkspaceProject.id.in_(ids),  # type: ignore[attr-defined]
                        WorkspaceProject.workspace_id == workspace_id,
                        WorkspaceProject.owner_id == owner_id,
                        WorkspaceProject.archived_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
            if len(rows) != len(ids):
                raise WorkflowError("invalid_project", "Project is outside workspace", 422)
        meeting = kind == "meeting"
        source = Source(
            id=source_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=kind,
            title=title,
            object_path=object_path,
            content_type=content_type,
            size_bytes=size_bytes,
            analysis_mode="agent",
            transcript_source="agent" if meeting else None,
            raw_transcript_text=text if meeting else None,
            content_text=text if not meeting else None,
            review_state=ReviewState.AWAITING_REVIEW if meeting else None,
            status=SourceStatus.AWAITING_REVIEW if meeting else SourceStatus.AWAITING_AGENT,
            processing_stage=(
                ProcessingStage.AWAITING_REVIEW if meeting else ProcessingStage.AWAITING_AGENT
            ),
            progress=0.45 if meeting else 0,
            project_id=ids[0] if ids else None,
        )
        if meeting and text:
            source.review_utterances = [
                AgentUtterance(id="initial", speaker_name="화자 1", text=text).model_dump(
                    mode="json", by_alias=True
                )
            ]
        self.session.add(source)
        await self.session.flush()
        for position, project_id in enumerate(ids):
            self.session.add(
                SourceProject(
                    workspace_id=workspace_id,
                    source_id=source.id,
                    project_id=project_id,
                    position=position,
                )
            )
        await self.session.commit()
        return source_info(source)

    async def create_text_source(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        title: str,
        text: str,
        kind: str = "document",
        project_ids: list[UUID] | None = None,
    ) -> SourceInfo:
        if not text.strip() or len(text.encode()) > self.settings.max_upload_bytes:
            raise WorkflowError("invalid_text", "Source text is empty or too large", 422)
        source_id = uuid4()
        path = f"inline:{source_id}"
        return await self._create_source(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_id=source_id,
            title=title,
            kind=kind,
            object_path=path,
            content_type="text/plain; charset=utf-8",
            size_bytes=len(text.encode()),
            text=text,
            project_ids=project_ids,
        )

    async def save_document_text(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: int,
        text: str,
    ) -> SourceInfo:
        source = await self.repository.source(owner_id, workspace_id, source_id, lock=True)
        if source.analysis_mode != "agent" or source.kind != "document":
            raise WorkflowError("invalid_source", "Agent document required", 409)
        if source.analysis_checkpoint is not None:
            raise WorkflowError("already_analyzed", "Analysis already started", 409)
        if source.review_revision != expected_revision:
            raise WorkflowError("stale_revision", "Source revision changed", 409)
        if not text.strip() or len(text.encode()) > self.settings.max_upload_bytes:
            raise WorkflowError("invalid_text", "Document text is empty or too large", 422)
        source.content_text = text.strip()
        source.review_revision += 1
        source.status = SourceStatus.AWAITING_AGENT
        source.processing_stage = ProcessingStage.AWAITING_AGENT
        self.session.add(source)
        await self.session.commit()
        return source_info(source)

    async def save_transcript(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: int,
        utterances: list[dict[str, Any] | AgentUtterance],
    ) -> SourceInfo:
        source = await self.repository.source(owner_id, workspace_id, source_id, lock=True)
        if (
            source.analysis_mode != "agent"
            or source.kind != "meeting"
            or source.review_state != ReviewState.AWAITING_REVIEW
        ):
            raise WorkflowError("review_closed", "Meeting is not awaiting review", 409)
        if source.review_revision != expected_revision:
            raise WorkflowError("stale_revision", "Transcript revision changed", 409)
        if len(utterances) > 1000:
            raise WorkflowError("invalid_transcript", "Too many utterances", 422)
        try:
            checked = [AgentUtterance.model_validate(item) for item in utterances]
        except ValidationError as exc:
            raise WorkflowError("invalid_transcript", "Invalid transcript", 422) from exc
        if len({item.id for item in checked}) != len(checked):
            raise WorkflowError("invalid_transcript", "Duplicate utterance ID", 422)
        source.review_utterances = [item.model_dump(mode="json", by_alias=True) for item in checked]
        if source.raw_transcript_text is None:
            source.raw_transcript_text = "\n\n".join(item.text for item in checked if item.text)
            source.raw_utterances = list(source.review_utterances)
        source.review_revision += 1
        self.session.add(source)
        await self.session.commit()
        return source_info(source)

    async def confirm_transcript(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: int,
    ) -> SourceInfo:
        source = await self.repository.source(owner_id, workspace_id, source_id, lock=True)
        if (
            source.analysis_mode != "agent"
            or source.kind != "meeting"
            or source.review_state != ReviewState.AWAITING_REVIEW
        ):
            raise WorkflowError("review_closed", "Meeting is not awaiting review", 409)
        if source.review_revision != expected_revision:
            raise WorkflowError("stale_revision", "Transcript revision changed", 409)
        utterances = [
            AgentUtterance.model_validate(item)
            for item in source.review_utterances
            if str(item.get("text", "")).strip()
        ]
        if not utterances:
            raise WorkflowError("text_required", "Transcript text is required", 422)
        snapshot = await self.repository.directory_snapshot(owner_id, workspace_id, source)
        source.transcript_text = "\n\n".join(
            f"{item.speaker_name}: {item.text}" for item in utterances
        )
        source.review_utterances = [
            item.model_dump(mode="json", by_alias=True) for item in utterances
        ]
        source.confirmed_snapshot = snapshot
        source.confirmed_at = datetime.now(UTC)
        source.association_revision += 1
        source.review_state = ReviewState.CONFIRMED
        source.status = SourceStatus.AWAITING_AGENT
        source.processing_stage = ProcessingStage.AWAITING_AGENT
        await self.repository.replace_participants(source)
        self.session.add(source)
        await self.session.commit()
        return source_info(source)

    async def analysis_context(
        self, *, owner_id: UUID, workspace_id: UUID, source_id: UUID
    ) -> AnalysisContext:
        source = await self.repository.source(owner_id, workspace_id, source_id)
        if source.analysis_mode != "agent":
            raise WorkflowError("invalid_source", "Agent source required", 409)
        text = _source_text(source)
        context_store = ContextStoreService(
            SqlContextStoreRepository(self.session),
            KeylessContextUpdater(),  # type: ignore[arg-type]
        )
        known = await context_store.current_decisions(workspace_id)
        directory = source.confirmed_snapshot or await self.repository.directory_snapshot(
            owner_id, workspace_id, source
        )
        return AnalysisContext(
            source=source_info(source),
            text=text,
            fingerprint=context_fingerprint(source, text, known, directory),
            known_decisions=known,
            directory=directory,
            extraction_schema=ExtractionResult.model_json_schema(),
            stage_schemas={
                "classification": ClassificationOutput.model_json_schema(),
                "entity": EntityOutput.model_json_schema(),
                "event": EventOutput.model_json_schema(),
                "relation": RelationOutput.model_json_schema(),
                "context": ContextOutput.model_json_schema(),
            },
        )

    async def _index_source_text(self, source: Source, text: str) -> None:
        normalizer = NormalizationService()
        segments: list[TranscriptSegment] | list[DocumentSection]
        if source.kind == "meeting":
            segments = [
                TranscriptSegment(
                    text=str(item["text"]),
                    speaker=str(item["speakerName"]),
                    start_seconds=item.get("startSeconds") or 0,
                    end_seconds=item.get("endSeconds") or item.get("startSeconds") or 0,
                )
                for item in source.review_utterances
                if str(item.get("text", "")).strip()
            ]
        else:
            segments = [DocumentSection(text=text)]
        normalized = normalizer.normalize(
            source.kind,
            source_id=source.id,
            workspace_id=source.workspace_id,
            title=source.title,
            segments=segments,
            metadata={"transcriptSource": source.transcript_source},
        )
        chunks = CharacterOverlapChunker(
            self.settings.chunk_size_chars, self.settings.chunk_overlap_chars
        ).chunk(normalized)
        if not chunks:
            raise WorkflowError("text_required", "No indexable text", 422)
        await self.session.execute(delete(Chunk).where(Chunk.source_id == source.id))
        for chunk in chunks:
            self.session.add(
                Chunk(
                    workspace_id=source.workspace_id,
                    source_id=source.id,
                    owner_id=source.owner_id,
                    position=chunk.position,
                    content=chunk.content,
                    start_seconds=chunk.start_seconds,
                    end_seconds=chunk.end_seconds,
                    embedding=None,
                )
            )

    async def submit_analysis(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: int,
        expected_fingerprint: str,
        result: dict[str, Any] | ExtractionResult,
    ) -> AnalysisSubmission:
        if self.session.bind is None:
            raise RuntimeError("Agent workflow session must be bound to PostgreSQL")
        # Reject foreign or missing sources before acquiring shared advisory locks.
        # Roll back the read transaction so a pool-size-one writer can progress.
        await self.repository.source(owner_id, workspace_id, source_id)
        await self.session.rollback()
        async with analysis_lock(self.session.bind, source_id, workspace_id):  # type: ignore[arg-type]
            return await self._submit_analysis_locked(
                owner_id=owner_id,
                workspace_id=workspace_id,
                source_id=source_id,
                expected_revision=expected_revision,
                expected_fingerprint=expected_fingerprint,
                result=result,
            )

    async def _submit_analysis_locked(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        source_id: UUID,
        expected_revision: int,
        expected_fingerprint: str,
        result: dict[str, Any] | ExtractionResult,
    ) -> AnalysisSubmission:
        source = await self.repository.source(owner_id, workspace_id, source_id, lock=True)
        if source.analysis_mode != "agent":
            raise WorkflowError("invalid_source", "Agent source required", 409)
        if source.review_revision != expected_revision:
            raise WorkflowError("stale_revision", "Source revision changed", 409)
        text = _source_text(source)
        directory = source.confirmed_snapshot or await self.repository.directory_snapshot(
            owner_id, workspace_id, source
        )
        current_source_fingerprint = source_fingerprint(source, text, directory)
        checkpoint = source.analysis_checkpoint
        if checkpoint is not None:
            if (
                checkpoint.get("mode") != "agent"
                or checkpoint.get("fingerprint") != current_source_fingerprint
                or checkpoint.get("context_fingerprint") != expected_fingerprint
            ):
                raise WorkflowError("analysis_conflict", "Source analysis differs", 409)
            try:
                replay = ExtractionResult.model_validate(result)
            except ValidationError as exc:
                raise WorkflowError("invalid_analysis", "Invalid extraction result", 422) from exc
            replay.warnings = []
            replay.usage = {}
            if checkpoint.get("result_hash") != result_fingerprint(replay):
                raise WorkflowError("analysis_conflict", "A different analysis already exists", 409)
            if checkpoint["phase"] == "done":
                return AnalysisSubmission(
                    source_id=source.id,
                    phase="done",
                    warnings=list(checkpoint.get("warnings", [])),
                    already_applied=True,
                )
            validated = ExtractionResult.model_validate(checkpoint["result"])
            graph = ResolvedGraph.model_validate(checkpoint["graph"])
        else:
            context_store = ContextStoreService(
                SqlContextStoreRepository(self.session),
                KeylessContextUpdater(),  # type: ignore[arg-type]
            )
            known = await context_store.current_decisions(workspace_id)
            if expected_fingerprint != context_fingerprint(source, text, known, directory):
                raise WorkflowError("stale_context", "Analysis context changed", 409)
            validated = validate_extraction(result, source=source, text=text, known_decisions=known)
            graph = None
            input_hash = result_fingerprint(validated)
            await self._index_source_text(source, text)
            source.status = SourceStatus.PROCESSING
            source.processing_stage = ProcessingStage.ANALYZING
            self.session.add(source)
            await self.session.commit()

        context_store = ContextStoreService(
            SqlContextStoreRepository(self.session),
            KeylessContextUpdater(),  # type: ignore[arg-type]
        )
        workspace = await self.repository.workspace(owner_id, workspace_id, lock=True)
        if checkpoint is not None:
            input_hash = checkpoint["result_hash"]
        graph_store = (
            Neo4jGraphStore.from_settings(self.settings) if self.settings.neo4j_enabled else None
        )
        try:

            async def save_extraction(
                extraction: ExtractionResult, resolved: ResolvedGraph, decision_fingerprint: str
            ) -> None:
                source.analysis_checkpoint = {
                    "mode": "agent",
                    "fingerprint": current_source_fingerprint,
                    "context_fingerprint": expected_fingerprint,
                    "decision_fingerprint": decision_fingerprint,
                    "result_hash": input_hash,
                    "phase": "extracted",
                    "result": extraction.model_dump(mode="json"),
                    "graph": resolved.model_dump(mode="json"),
                }
                source.processing_stage = ProcessingStage.ANALYZING
                self.session.add(source)
                await self.session.commit()

            async def save_context(warnings: list[str]) -> None:
                source.analysis_checkpoint = {
                    **source.analysis_checkpoint,
                    "phase": "context_applied",
                    "context_warnings": warnings,
                }
                source.processing_stage = ProcessingStage.GRAPHING
                self.session.add(source)
                await self.session.commit()

            warnings = await analyze_source(
                adapter=None,
                api_key="",
                model="",
                context_store=context_store,
                graph_store=graph_store,
                workspace_id=workspace_id,
                owner_id=owner_id,
                source_id=source.id,
                title=source.title,
                subject=workspace.name,
                text=text,
                directory_snapshot=directory,
                result=validated,
                resolved_graph=graph,
                context_applied=checkpoint is not None and checkpoint["phase"] == "context_applied",
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
            source.status = SourceStatus.SUCCEEDED
            source.processing_stage = ProcessingStage.COMPLETED
            source.progress = 1
            self.session.add(source)
            await self.session.commit()
        finally:
            if graph_store is not None:
                await graph_store.close()
        return AnalysisSubmission(
            source_id=source.id, phase="done", warnings=warnings, already_applied=False
        )

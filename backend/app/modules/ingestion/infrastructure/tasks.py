import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote
from uuid import UUID

import httpx
from celery import Task
from sqlalchemy import text
from sqlmodel import select

from app.core.celery import celery_app
from app.core.config import get_settings
from app.core.database import engine, session_factory
from app.modules.ingestion.application.document_parser import DocumentParser
from app.modules.ingestion.application.pipeline import IngestionPipeline
from app.modules.ingestion.application.source_analysis import SourceAnalysisService
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.workspaces.domain.source_state import (
    ProcessingStage,
    ReviewState,
    SourceStatus,
)
from app.modules.workspaces.infrastructure.models import Source


@asynccontextmanager
async def _source_execution_lock(source_id: UUID) -> AsyncIterator[None]:
    """Hold a blocking transaction advisory lock across every source-write commit.

    This dedicated transaction pins a backend connection even through a transaction
    pooler. Source writes use other sessions. A duplicate waits and then rechecks
    persisted state; a worker death rolls the transaction back and releases the lock.
    """
    key = int.from_bytes(source_id.bytes[:8], "big", signed=True)
    async with engine.connect() as connection:
        await connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
        await connection.execute(text("SET LOCAL statement_timeout = 0"))
        await connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        try:
            yield
        finally:
            await connection.rollback()


async def _download_source(source: Source) -> bytes:
    settings = get_settings()
    service_key = settings.supabase_service_role_key.get_secret_value()
    if not service_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다.")
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/authenticated/"
        f"{settings.supabase_storage_bucket}/{quote(source.object_path, safe='/')}"
    )
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, headers=headers)
    response.raise_for_status()
    return response.content


async def _update_source(
    source_id: UUID,
    *,
    status: SourceStatus,
    stage: ProcessingStage,
    progress: float,
    error_message: str | None = None,
) -> None:
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return
        if (
            source.status == SourceStatus.SUCCEEDED
            or source.review_state == ReviewState.AWAITING_REVIEW
        ):
            return
        source.status = status
        if source.review_state == ReviewState.CONFIRMED:
            source.processing_stage = ProcessingStage.CONFIRMED
        elif source.review_state == ReviewState.TRANSCRIBING:
            source.processing_stage = ProcessingStage.TRANSCRIBING
        else:
            source.processing_stage = stage
        source.progress = progress
        source.error_message = error_message
        session.add(source)
        await session.commit()


async def _process_source(source_id: UUID) -> None:
    async with session_factory() as session:
        result = await session.exec(select(Source).where(Source.id == source_id).with_for_update())
        source = result.first()
        if source is None:
            raise ValueError(f"Source not found: {source_id}")
        if source.status in {SourceStatus.SUCCEEDED, SourceStatus.AWAITING_REVIEW}:
            return
        if source.kind == "meeting" and source.review_state not in {
            ReviewState.TRANSCRIBING,
            ReviewState.CONFIRMED,
        }:
            return
        source.status = SourceStatus.PROCESSING
        source.error_message = None
        pipeline = IngestionPipeline()

        if source.analysis_checkpoint is not None:
            # Extraction was committed before either sink was written. Resume that
            # exact result without replacing chunks or calling providers again.
            graph_text = (
                source.content_text if source.kind == "document" else source.transcript_text
            ) or ""
            source.processing_stage = ProcessingStage.GRAPHING
            source.progress = 0.7
            session.add(source)
            await session.commit()
            await SourceAnalysisService().run(session, source=source, text=graph_text)
            source.status = SourceStatus.SUCCEEDED
            source.processing_stage = ProcessingStage.COMPLETED
            source.progress = 1
            session.add(source)
            await session.commit()
            return

        if source.kind == "document":
            source.processing_stage = ProcessingStage.UPLOADED
            source.progress = 0.2
            await session.commit()
            content = await _download_source(source)
            parsed_text = DocumentParser().parse(content, filename=source.title)
            graph_text = parsed_text
            source.content_text = parsed_text
            source.processing_stage = ProcessingStage.ANALYZING
            source.progress = 0.5
            session.add(source)
            await session.commit()
            await pipeline.index_source(
                session,
                source=source,
                segments=[DocumentSection(text=parsed_text)],
            )
        elif source.review_state == ReviewState.TRANSCRIBING:
            source.processing_stage = ProcessingStage.TRANSCRIBING
            source.progress = 0.2
            await session.commit()
            content = await _download_source(source)
            transcription = await pipeline.transcribe(
                session,
                source=source,
                audio=content,
                filename=source.title,
                content_type=source.content_type,
            )
            source.raw_transcript_text = transcription.text
            source.duration_seconds = transcription.duration_seconds
            source.raw_utterances = [
                {
                    "id": f"server-{index}",
                    "personId": None,
                    "speakerName": item.speaker or "화자 1",
                    "text": item.text,
                    "startSeconds": item.start_seconds,
                    "endSeconds": item.end_seconds,
                }
                for index, item in enumerate(transcription.segments)
            ] or [
                {
                    "id": "server-0",
                    "personId": None,
                    "speakerName": "화자 1",
                    "text": transcription.text,
                    "startSeconds": 0,
                    "endSeconds": transcription.duration_seconds or 0,
                }
            ]
            if not source.review_utterances:
                source.review_utterances = list(source.raw_utterances)
            source.review_state = ReviewState.AWAITING_REVIEW
            source.status = SourceStatus.AWAITING_REVIEW
            source.processing_stage = ProcessingStage.AWAITING_REVIEW
            source.progress = 0.45
            session.add(source)
            await session.commit()
            return
        else:
            graph_text = source.transcript_text or ""
            if source.review_state != ReviewState.CONFIRMED:
                return
            source.processing_stage = ProcessingStage.ANALYZING
            source.progress = 0.5
            await session.commit()
            segments = [
                TranscriptSegment(
                    text=str(item["text"]),
                    speaker=str(item["speakerName"]),
                    start_seconds=item.get("startSeconds") or 0,
                    end_seconds=item.get("endSeconds") or item.get("startSeconds") or 0,
                )
                for item in source.review_utterances
                if item.get("text", "").strip()
            ]
            await pipeline.index_source(
                session,
                source=source,
                segments=segments,
            )

        source.processing_stage = ProcessingStage.GRAPHING
        source.progress = 0.7
        session.add(source)
        await session.commit()
        await SourceAnalysisService().run(session, source=source, text=graph_text)

        source.status = SourceStatus.PROCESSING
        source.processing_stage = ProcessingStage.GRAPHING
        source.progress = 0.9
        session.add(source)
        await session.commit()
        source.status = SourceStatus.SUCCEEDED
        source.processing_stage = ProcessingStage.COMPLETED
        source.progress = 1
        session.add(source)
        await session.commit()


async def _run_source_attempt(source_id: UUID, *, final_attempt: bool) -> Exception | None:
    async with _source_execution_lock(source_id):
        try:
            await _process_source(source_id)
        except Exception as exc:
            # Commit retry/failure before releasing the lock so a duplicate
            # cannot start while this attempt still appears to be processing.
            await _update_source(
                source_id,
                status=SourceStatus.FAILED if final_attempt else SourceStatus.QUEUED,
                stage=ProcessingStage.UPLOADED,
                progress=0,
                error_message=str(exc),
            )
            return exc
    return None


@celery_app.task(
    bind=True,
    name="ingestion.process_source",
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_source(self: Task, source_id: str, app_attempt: int = 0) -> None:
    identifier = UUID(source_id)
    final_attempt = app_attempt >= self.max_retries
    try:
        error = asyncio.run(_run_source_attempt(identifier, final_attempt=final_attempt))
    except Exception as exc:
        # The lock/DB connection failed; leave source state untouched and keep
        # retrying infrastructure recovery. The normal three-attempt provider
        # bound below must not acknowledge a persisted `processing` source.
        raise self.retry(
            exc=exc,
            countdown=30,
            max_retries=2_147_483_647,
            kwargs={"app_attempt": app_attempt},
        ) from exc
    if error is not None:
        if final_attempt:
            raise error
        raise self.retry(
            exc=error,
            max_retries=2_147_483_647,
            kwargs={"app_attempt": app_attempt + 1},
        ) from error

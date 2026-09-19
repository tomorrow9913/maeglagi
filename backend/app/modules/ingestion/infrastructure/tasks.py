import asyncio
from urllib.parse import quote
from uuid import UUID

import httpx
from celery import Task
from sqlmodel import select

from app.core.celery import celery_app
from app.core.config import get_settings
from app.core.database import session_factory
from app.modules.ingestion.application.document_parser import DocumentParser
from app.modules.ingestion.application.pipeline import IngestionPipeline
from app.modules.ingestion.application.source_analysis import SourceAnalysisService
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.workspaces.infrastructure.models import Source


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
    status: str,
    stage: str,
    progress: float,
    error_message: str | None = None,
) -> None:
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return
        if source.status == "succeeded" or source.review_state == "awaiting_review":
            return
        source.status = status
        source.processing_stage = "confirmed" if source.review_state == "confirmed" else stage
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
        if source.status in {"succeeded", "processing", "awaiting_review"}:
            return
        if source.kind == "meeting" and source.review_state not in {"transcribing", "confirmed"}:
            return
        source.status = "processing"
        source.error_message = None
        pipeline = IngestionPipeline()

        if source.kind == "document":
            source.processing_stage = "uploaded"
            source.progress = 0.2
            await session.commit()
            content = await _download_source(source)
            parsed_text = DocumentParser().parse(content, filename=source.title)
            graph_text = parsed_text
            source.content_text = parsed_text
            source.processing_stage = "analyzing"
            source.progress = 0.5
            session.add(source)
            await session.commit()
            await pipeline.index_source(
                session,
                source=source,
                segments=[DocumentSection(text=parsed_text)],
            )
        elif source.review_state == "transcribing":
            source.processing_stage = "transcribing"
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
            source.review_state = "awaiting_review"
            source.status = "awaiting_review"
            source.processing_stage = "awaiting_review"
            source.progress = 0.45
            session.add(source)
            await session.commit()
            return
        else:
            graph_text = source.transcript_text or ""
            if source.review_state != "confirmed":
                return
            source.processing_stage = "analyzing"
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

        source.processing_stage = "graphing"
        source.progress = 0.7
        session.add(source)
        await session.commit()
        await SourceAnalysisService().run(session, source=source, text=graph_text)

        source.status = "processing"
        source.processing_stage = "graphing"
        source.progress = 0.9
        session.add(source)
        await session.commit()
        source.status = "succeeded"
        source.processing_stage = "completed"
        source.progress = 1
        session.add(source)
        await session.commit()


@celery_app.task(
    bind=True,
    name="ingestion.process_source",
    max_retries=3,
    default_retry_delay=10,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_source(self: Task, source_id: str) -> None:
    identifier = UUID(source_id)
    try:
        asyncio.run(_process_source(identifier))
    except Exception as exc:
        final_attempt = self.request.retries >= self.max_retries
        asyncio.run(
            _update_source(
                identifier,
                status="failed" if final_attempt else "queued",
                stage="uploaded",
                progress=0,
                error_message=str(exc),
            )
        )
        if final_attempt:
            raise
        raise self.retry(exc=exc) from exc

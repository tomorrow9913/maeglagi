"""Executor-neutral source processing with advisory locks and checkpoints."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.config import get_settings
from app.core.database import engine, session_factory
from app.modules.context_engine.application.extraction import ExtractionError
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.ingestion.application.document_parser import DocumentParser
from app.modules.ingestion.application.pipeline import (
    IngestionError,
    IngestionPipeline,
    MissingCapabilityCredentialError,
)
from app.modules.ingestion.application.source_analysis import SourceAnalysisService
from app.modules.ingestion.domain.models import DocumentSection, TranscriptSegment
from app.modules.workspaces.domain.source_state import (
    ProcessingStage,
    ReviewState,
    SourceStatus,
)
from app.modules.workspaces.infrastructure.models import Source

_CAPABILITIES = frozenset({"chat", "embedding", "transcription", "structuredOutput"})
_PROVIDERS = frozenset({"openai", "anthropic", "nvidia", "ollama"})
_EXTRACTION_STAGES = frozenset(
    {"classification", "entity", "event", "relation", "context", "context_update"}
)
_MISSING_TRANSCRIPTION_MESSAGE = "음성 변환을 지원하는 프로바이더 연결 및 모델 설정이 필요합니다."
_GENERIC_FAILURE_MESSAGE = "소스 처리에 실패했습니다. 설정을 확인한 뒤 다시 시도해 주세요."


class SafeAttemptError(RuntimeError):
    """Retry-compatible failure carrying only vetted diagnostic fields."""

    def __init__(
        self,
        *,
        code: str,
        stage: str,
        error_type: str,
        cause_type: str | None = None,
        http_status: int | None = None,
        capability: str | None = None,
        provider: str | None = None,
        extraction_stage: str | None = None,
        terminal: bool = False,
        provider_failure: bool = False,
    ) -> None:
        message = (
            _MISSING_TRANSCRIPTION_MESSAGE
            if code == "missing_capability_credential" and capability == "transcription"
            else _GENERIC_FAILURE_MESSAGE
        )
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.error_type = error_type
        self.cause_type = cause_type
        self.http_status = http_status
        self.capability = capability
        self.provider = provider
        self.extraction_stage = extraction_stage
        self.terminal = terminal
        self.provider_failure = provider_failure


def _safe_attempt_error(exc: Exception, stage: str) -> SafeAttemptError:
    chain: list[Exception] = []
    current: BaseException | None = exc
    while (
        isinstance(current, Exception)
        and all(current is not item for item in chain)
        and len(chain) < 8
    ):
        chain.append(current)
        current = current.__cause__
    cause = chain[-1]
    capability = next(
        (
            value
            for item in chain
            if isinstance(value := getattr(item, "capability", None), str)
            and value in _CAPABILITIES
        ),
        None,
    )
    provider = None
    extraction_stage = next(
        (
            item.stage
            for item in chain
            if isinstance(item, ExtractionError) and item.stage in _EXTRACTION_STAGES
        ),
        None,
    )
    for item in chain:
        value = getattr(item, "provider", None)
        if isinstance(item, MissingCapabilityCredentialError) and item.providers:
            value = item.providers[0] if len(item.providers) == 1 else None
        if isinstance(value, str) and value in _PROVIDERS:
            provider = value
            break
    missing_credential = any(isinstance(item, MissingCapabilityCredentialError) for item in chain)
    provider_failure = any(isinstance(item, ProviderError) for item in chain)
    status = next(
        (
            item.response.status_code
            for item in chain
            if isinstance(item, httpx.HTTPStatusError) and 100 <= item.response.status_code <= 599
        ),
        None,
    )
    if status is None:
        status = next(
            (
                item.http_status
                for item in chain
                if isinstance(item, ProviderError)
                and isinstance(item.http_status, int)
                and 400 <= item.http_status <= 599
            ),
            None,
        )
    if missing_credential and capability is not None:
        code = "missing_capability_credential"
    elif status is not None:
        code = "http_status"
    elif any(isinstance(item, httpx.TimeoutException) for item in chain):
        code = "http_timeout"
    elif any(isinstance(item, httpx.ConnectError) for item in chain):
        code = "http_connect"
    elif any(isinstance(item, ProviderError) for item in chain):
        code = "provider_error"
    elif isinstance(exc, IngestionError):
        code = "ingestion_error"
    else:
        code = "processing_error"
    result = SafeAttemptError(
        code=code,
        stage=stage,
        error_type=type(exc).__name__,
        cause_type=type(cause).__name__ if cause is not exc else None,
        http_status=status,
        capability=capability if code == "missing_capability_credential" else None,
        provider=provider,
        extraction_stage=extraction_stage,
        terminal=code == "missing_capability_credential"
        or (provider_failure and status in {401, 403, 404}),
        provider_failure=provider_failure,
    )
    # Preserve source locations for Sentry without retaining the original
    # exception, arguments, response body, or frame locals in the error object.
    return result.with_traceback(exc.__traceback__)


@asynccontextmanager
async def _source_execution_lock(source_id: UUID) -> AsyncIterator[None]:
    """Hold source and workspace locks across every source-write commit.

    This dedicated transaction pins a backend connection even through a transaction
    pooler. Source writes use other sessions. A duplicate waits and then rechecks
    persisted state; a worker death rolls the transaction back and releases the lock.
    """
    # Reserve the sign bit as a namespace: source keys are nonnegative and
    # workspace keys are negative, so the two lock classes cannot overlap.
    source_key = int.from_bytes(source_id.bytes[:8], "big") & ((1 << 63) - 1)
    async with engine.connect() as connection:
        await connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
        await connection.execute(text("SET LOCAL statement_timeout = 0"))
        await connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": source_key})
        result = await connection.execute(
            text("SELECT workspace_id FROM sources WHERE id = :source_id"),
            {"source_id": source_id},
        )
        workspace_id = result.scalar_one_or_none()
        if workspace_id is not None:
            workspace_key = (int.from_bytes(workspace_id.bytes[:8], "big") & ((1 << 63) - 1)) - (
                1 << 63
            )
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": workspace_key}
            )
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
) -> str:
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return "unknown"
        if (
            source.status == SourceStatus.SUCCEEDED
            or source.review_state == ReviewState.AWAITING_REVIEW
        ):
            return str(source.processing_stage)
        previous_stage = str(source.processing_stage)
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
        return previous_stage


async def _process_source(source_id: UUID) -> None:
    async with session_factory() as session:
        result = await session.exec(select(Source).where(Source.id == source_id).with_for_update())
        source = result.first()
        if source is None:
            raise ValueError(f"Source not found: {source_id}")
        if source.analysis_mode == "agent":
            return
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
            parsed_text = await asyncio.to_thread(
                DocumentParser().parse, content, filename=source.title
            )
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


async def process_source_attempt(source_id: UUID, *, final_attempt: bool) -> Exception | None:
    async with _source_execution_lock(source_id):
        try:
            await _process_source(source_id)
        except DBAPIError:
            # SQL failures belong to infrastructure retry even if the database
            # recovers before the later status update would have succeeded.
            raise
        except Exception as exc:
            # Commit retry/failure before releasing the lock so a duplicate
            # cannot start while this attempt still appears to be processing.
            typed_capability = getattr(exc, "capability", None)
            missing_credential = (
                isinstance(exc, MissingCapabilityCredentialError)
                and isinstance(typed_capability, str)
                and typed_capability in _CAPABILITIES
            )
            safe_error = _safe_attempt_error(exc, "processing")
            message = _GENERIC_FAILURE_MESSAGE
            if safe_error.provider_failure and safe_error.http_status == 404:
                message = (
                    "설정된 모델을 사용할 수 없습니다. 워크스페이스의 추출 모델을 선택해 주세요."
                )
            elif safe_error.provider_failure and safe_error.http_status in {401, 403}:
                message = "AI 연결 인증에 실패했습니다. 계정의 API 키와 접근 권한을 확인해 주세요."
            stage = await _update_source(
                source_id,
                status=(
                    SourceStatus.FAILED
                    if final_attempt or safe_error.terminal
                    else SourceStatus.QUEUED
                ),
                stage=ProcessingStage.UPLOADED,
                progress=0,
                error_message=(
                    _MISSING_TRANSCRIPTION_MESSAGE
                    if missing_credential and typed_capability == "transcription"
                    else message
                ),
            )
            safe_error.stage = stage
            return safe_error
    return None

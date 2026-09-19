"""Recover a failed recording with user-reviewed browser transcription."""

from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.repositories import WorkflowRepository
from app.modules.agent_workflows.schemas import AgentUtterance
from app.modules.ingestion.infrastructure.pg_jobs import ProcessingJob
from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import Source, WorkspacePerson


async def recover_browser_transcript(
    session: AsyncSession,
    *,
    owner_id: UUID,
    workspace_id: UUID,
    source_id: UUID,
    revision: int,
    utterances: list[AgentUtterance],
) -> Source:
    source = await WorkflowRepository(session).source(owner_id, workspace_id, source_id, lock=True)
    if (
        source.kind != "meeting"
        or source.status != SourceStatus.FAILED
        or source.review_state != ReviewState.TRANSCRIBING
        or source.analysis_mode != "server"
    ):
        raise WorkflowError("recovery_unavailable", "Failed transcription required", 409)
    if source.review_revision != revision:
        raise WorkflowError("stale_revision", "Transcript revision changed", 409)
    stored_prefix = f"{owner_id}/{workspace_id}/{source_id}/"
    if source.size_bytes <= 0 or not source.object_path.startswith(stored_prefix):
        raise WorkflowError("recording_missing", "Stored recording not found", 409)
    job = await session.get(ProcessingJob, source_id, with_for_update=True)
    if job is not None and job.status in {"pending", "running"}:
        raise WorkflowError("processing_active", "Transcription is still running", 409)
    if not utterances or len(utterances) > 1000 or not any(row.text for row in utterances):
        raise WorkflowError("invalid_transcript", "Transcript text is required", 422)
    if len({row.id for row in utterances}) != len(utterances):
        raise WorkflowError("invalid_transcript", "Duplicate utterance ID", 422)
    for person_id in {row.person_id for row in utterances if row.person_id is not None}:
        person = await session.get(WorkspacePerson, person_id, with_for_update=True)
        if (
            person is None
            or person.owner_id != owner_id
            or person.workspace_id != workspace_id
            or person.archived_at is not None
        ):
            raise WorkflowError("invalid_person", "Active workspace participant required", 422)
    rows = [row.model_dump(mode="json", by_alias=True) for row in utterances]
    source.review_utterances = rows
    # Keep the recording and any earlier raw transcript intact for comparison.
    if not source.raw_transcript_text:
        source.raw_transcript_text = "\n\n".join(
            f"{row.speaker_name}: {row.text}" for row in utterances if row.text
        )
        source.raw_utterances = list(rows)
    source.transcript_source = "browser"
    source.review_revision += 1
    source.review_state = ReviewState.AWAITING_REVIEW
    source.status = SourceStatus.AWAITING_REVIEW
    source.processing_stage = ProcessingStage.AWAITING_REVIEW
    source.progress = 0.45
    source.error_message = None
    session.add(source)
    # No enqueue, provider call, source duplication, or automatic confirmation.
    await session.commit()
    return source

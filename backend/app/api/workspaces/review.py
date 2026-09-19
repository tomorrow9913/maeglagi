"""Editable meeting transcript review, with an explicit processing gate."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces.directory import active_person, active_project, owned_workspace
from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.ingestion.infrastructure.tasks import process_source
from app.modules.workspaces.infrastructure.models import Source, WorkspacePerson, WorkspaceProject

router = APIRouter(prefix="/{workspace_id}/sources/{source_id}/review")
Session = Annotated[AsyncSession, Depends(get_session)]


class ReviewUtterance(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, max_length=80)
    person_id: UUID | None = Field(
        default=None, validation_alias="personId", serialization_alias="personId"
    )
    speaker_name: str = Field(
        min_length=1,
        max_length=120,
        validation_alias="speakerName",
        serialization_alias="speakerName",
    )
    text: str = Field(max_length=10000)
    start_seconds: float | None = Field(
        default=None, ge=0, validation_alias="startSeconds", serialization_alias="startSeconds"
    )
    end_seconds: float | None = Field(
        default=None, ge=0, validation_alias="endSeconds", serialization_alias="endSeconds"
    )

    @model_validator(mode="after")
    def clean(self) -> "ReviewUtterance":
        self.id = self.id.strip()
        self.speaker_name = self.speaker_name.strip()
        self.text = self.text.strip()
        if not self.id or not self.speaker_name:
            raise ValueError("Utterance ID and speaker name are required")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("Utterance end precedes start")
        return self


class LiveDraft(BaseModel):
    utterances: list[ReviewUtterance] = Field(max_length=1000)


class ReviewPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    revision: int = Field(ge=0)
    project_id: UUID | None = Field(validation_alias="projectId")
    utterances: list[ReviewUtterance] = Field(max_length=1000)


class ConfirmRequest(BaseModel):
    revision: int = Field(ge=0)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: UUID = Field(serialization_alias="sourceId")
    title: str
    transcript_source: str | None = Field(serialization_alias="transcriptSource")
    review_state: str = Field(serialization_alias="reviewState")
    revision: int
    project_id: UUID | None = Field(serialization_alias="projectId")
    utterances: list[ReviewUtterance]
    raw_transcript_text: str | None = Field(serialization_alias="rawTranscriptText")
    raw_utterances: list[ReviewUtterance] = Field(serialization_alias="rawUtterances")
    confirmed_at: datetime | None = Field(serialization_alias="confirmedAt")
    confirmed_snapshot: dict[str, Any] | None = Field(serialization_alias="confirmedSnapshot")


def validate_unique_utterances(utterances: list[ReviewUtterance]) -> None:
    ids = [item.id for item in utterances]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate utterance ID")


def review_payload(source: Source) -> ReviewResponse:
    return ReviewResponse(
        source_id=source.id,
        title=source.title,
        transcript_source=source.transcript_source,
        review_state=source.review_state
        or ("confirmed" if source.status == "succeeded" else "awaiting_review"),
        revision=source.review_revision,
        project_id=source.project_id,
        utterances=[ReviewUtterance.model_validate(item) for item in source.review_utterances],
        raw_transcript_text=source.raw_transcript_text,
        raw_utterances=[ReviewUtterance.model_validate(item) for item in source.raw_utterances],
        confirmed_at=source.confirmed_at,
        confirmed_snapshot=source.confirmed_snapshot,
    )


def job_payload(source: Source) -> JobResponse:
    return JobResponse(
        id=source.id,
        source_id=source.id,
        source_kind=source.kind,
        transcript_source=source.transcript_source,
        status=source.status,
        progress=source.progress,
        stage=source.processing_stage,
        error_message=source.error_message,
    )


async def owned_meeting(
    session: AsyncSession,
    workspace_id: UUID,
    source_id: UUID,
    owner_id: UUID,
    *,
    lock: bool = False,
) -> Source:
    await owned_workspace(session, workspace_id, owner_id)
    if lock:
        result = await session.exec(select(Source).where(Source.id == source_id).with_for_update())
        source = result.first()
    else:
        source = await session.get(Source, source_id)
    if (
        source is None
        or source.workspace_id != workspace_id
        or source.owner_id != owner_id
        or source.kind != "meeting"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meeting not found")
    return source


async def validate_refs(
    session: AsyncSession,
    workspace_id: UUID,
    owner_id: UUID,
    project_id: UUID | None,
    utterances: list[ReviewUtterance],
    *,
    lock: bool = False,
) -> tuple[WorkspaceProject | None, dict[UUID, WorkspacePerson]]:
    project = await active_project(session, project_id, workspace_id, owner_id, lock=lock)
    people: dict[UUID, WorkspacePerson] = {}
    for item in utterances:
        if item.person_id is not None and item.person_id not in people:
            person = await active_person(session, item.person_id, workspace_id, owner_id, lock=lock)
            assert person is not None
            people[item.person_id] = person
    return project, people


def _snapshot(
    project: WorkspaceProject,
    people: dict[UUID, WorkspacePerson],
    project_owner: WorkspacePerson | None,
) -> dict[str, Any]:
    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "goal": project.goal,
            "description": project.description,
            "ownerPersonId": str(project.owner_person_id) if project.owner_person_id else None,
            "ownerName": project_owner.name if project_owner else None,
            "ownerRole": project_owner.role if project_owner else None,
            "startsOn": project.starts_on.isoformat() if project.starts_on else None,
            "endsOn": project.ends_on.isoformat() if project.ends_on else None,
        },
        "people": [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "aliases": list(person.aliases),
            }
            for person in people.values()
        ],
    }


@router.get("", response_model=ReviewResponse)
async def get_review(
    workspace_id: UUID, source_id: UUID, user: CurrentUser, session: Session
) -> ReviewResponse:
    return review_payload(await owned_meeting(session, workspace_id, source_id, user.id))


@router.patch("", response_model=ReviewResponse)
async def save_review(
    workspace_id: UUID, source_id: UUID, body: ReviewPatch, user: CurrentUser, session: Session
) -> ReviewResponse:
    source = await owned_meeting(session, workspace_id, source_id, user.id, lock=True)
    if source.review_state != "awaiting_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting is not awaiting review")
    if source.review_revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale review revision")
    validate_unique_utterances(body.utterances)
    await validate_refs(session, workspace_id, user.id, body.project_id, body.utterances, lock=True)
    source.project_id = body.project_id
    source.review_utterances = [
        item.model_dump(by_alias=True, mode="json") for item in body.utterances
    ]
    source.review_revision += 1
    session.add(source)
    await session.commit()
    return review_payload(source)


@router.post("/confirm", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def confirm_review(
    workspace_id: UUID, source_id: UUID, body: ConfirmRequest, user: CurrentUser, session: Session
) -> JobResponse:
    source = await owned_meeting(session, workspace_id, source_id, user.id, lock=True)
    if source.review_revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale review revision")
    if source.review_state == "confirmed":
        if source.status not in {"failed", "enqueue_pending"}:
            return job_payload(source)
    elif source.review_state == "awaiting_review":
        utterances = [ReviewUtterance.model_validate(item) for item in source.review_utterances]
        validate_unique_utterances(utterances)
        usable = [item for item in utterances if item.text]
        if not usable:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transcript text is required")
        project, people = await validate_refs(
            session, workspace_id, user.id, source.project_id, usable, lock=True
        )
        if project is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Project selection is required"
            )
        project_owner = None
        if project.owner_person_id is not None:
            project_owner = await session.get(
                WorkspacePerson,
                project.owner_person_id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                project_owner is None
                or project_owner.workspace_id != workspace_id
                or project_owner.owner_id != user.id
            ):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid project owner")
        for item in usable:
            if item.person_id is not None:
                item.speaker_name = people[item.person_id].name
        source.review_utterances = [item.model_dump(by_alias=True, mode="json") for item in usable]
        source.transcript_text = "\n\n".join(f"{item.speaker_name}: {item.text}" for item in usable)
        source.confirmed_snapshot = _snapshot(project, people, project_owner)
        source.confirmed_at = datetime.now(UTC)
        source.review_state = "confirmed"
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting is not awaiting review")
    source.status = "enqueue_pending"
    source.processing_stage = "confirmed"
    source.error_message = None
    session.add(source)
    # Keep the source row locked through broker publication. Another confirmation
    # waits, then sees queued or failed; the worker cannot race an uncommitted gate.
    await session.flush()
    try:
        process_source.apply_async(args=[str(source.id)], task_id=str(source.id))
    except (OperationalError, ConnectionError) as exc:
        source.status = "failed"
        source.error_message = "Processing queue unavailable"
        session.add(source)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Processing queue unavailable"
        ) from exc
    source.status = "queued"
    session.add(source)
    await session.commit()
    return job_payload(source)

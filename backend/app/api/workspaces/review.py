"""Editable meeting transcript review, with an explicit processing gate."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.api.workspaces.associations import project_ids, replace_projects
from app.api.workspaces.directory import active_person, active_project, owned_workspace
from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.ingestion.infrastructure.tasks import process_source
from app.modules.workspaces.domain.source_state import (
    ProcessingStage,
    ReviewState,
    SourceStatus,
)
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    WorkspacePerson,
    WorkspaceProject,
)

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
    project_id: UUID | None = Field(default=None, validation_alias="projectId")
    project_ids: list[UUID] | None = Field(default=None, validation_alias="projectIds")
    utterances: list[ReviewUtterance] = Field(max_length=1000)


class ConfirmRequest(BaseModel):
    revision: int = Field(ge=0)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_id: UUID = Field(serialization_alias="sourceId")
    title: str
    transcript_source: str | None = Field(serialization_alias="transcriptSource")
    review_state: ReviewState = Field(serialization_alias="reviewState")
    status: SourceStatus
    stage: ProcessingStage
    error_message: str | None = Field(serialization_alias="errorMessage")
    revision: int
    project_id: UUID | None = Field(serialization_alias="projectId")
    project_ids: list[UUID] = Field(serialization_alias="projectIds")
    suggested_participants: list[dict[str, Any]] = Field(
        default_factory=list, serialization_alias="suggestedParticipants"
    )
    utterances: list[ReviewUtterance]
    raw_transcript_text: str | None = Field(serialization_alias="rawTranscriptText")
    raw_utterances: list[ReviewUtterance] = Field(serialization_alias="rawUtterances")
    confirmed_at: datetime | None = Field(serialization_alias="confirmedAt")
    confirmed_snapshot: dict[str, Any] | None = Field(serialization_alias="confirmedSnapshot")


def validate_unique_utterances(utterances: list[ReviewUtterance]) -> None:
    ids = [item.id for item in utterances]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate utterance ID")


def review_payload(
    source: Source,
    selected_projects: list[UUID] | None = None,
    suggested: list[dict[str, Any]] | None = None,
) -> ReviewResponse:
    return ReviewResponse(
        source_id=source.id,
        title=source.title,
        transcript_source=source.transcript_source,
        review_state=source.review_state
        or (
            ReviewState.CONFIRMED
            if source.status == SourceStatus.SUCCEEDED
            else ReviewState.AWAITING_REVIEW
        ),
        status=source.status,
        stage=source.processing_stage,
        error_message=source.error_message,
        revision=source.review_revision,
        project_id=source.project_id,
        project_ids=selected_projects
        if selected_projects is not None
        else ([source.project_id] if source.project_id else []),
        suggested_participants=suggested or [],
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
    projects: list[WorkspaceProject],
    people: dict[UUID, WorkspacePerson],
    project_owners: dict[UUID, WorkspacePerson],
    roster: dict[UUID, WorkspacePerson] | None = None,
) -> dict[str, Any]:
    project_rows = [
        {
            "id": str(project.id),
            "name": project.name,
            "goal": project.goal,
            "description": project.description,
            "ownerPersonId": str(project.owner_person_id) if project.owner_person_id else None,
            "ownerName": project_owners[project.owner_person_id].name
            if project.owner_person_id in project_owners
            else None,
            "ownerRole": project_owners[project.owner_person_id].role
            if project.owner_person_id in project_owners
            else None,
            "startsOn": project.starts_on.isoformat() if project.starts_on else None,
            "endsOn": project.ends_on.isoformat() if project.ends_on else None,
        }
        for project in projects
    ]
    return {
        "project": project_rows[0] if project_rows else None,
        "projects": project_rows,
        "people": [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "email": person.email,
                "aliases": list(person.aliases),
            }
            for person in people.values()
        ],
        "roster": [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "email": person.email,
                "aliases": list(person.aliases),
            }
            for person in (roster or {}).values()
        ],
    }


async def review_payload_with_directory(session: AsyncSession, source: Source) -> ReviewResponse:
    ids = await project_ids(session, source)
    if not ids:
        return review_payload(source, [])
    rows = (
        await session.exec(
            select(WorkspacePerson)
            .join(ProjectMember, ProjectMember.person_id == WorkspacePerson.id)
            .join(WorkspaceProject, WorkspaceProject.id == ProjectMember.project_id)
            .where(
                ProjectMember.project_id.in_(ids),  # type: ignore[attr-defined]
                WorkspacePerson.workspace_id == source.workspace_id,
                WorkspacePerson.archived_at.is_(None),  # type: ignore[union-attr]
                WorkspaceProject.archived_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    seen: set[str] = set()
    suggested: list[dict[str, Any]] = []
    for person in rows:
        key = person.email_normalized or str(person.id)
        if key in seen:
            continue
        seen.add(key)
        suggested.append(
            {
                "id": person.id,
                "workspaceId": person.workspace_id,
                "name": person.name,
                "email": person.email,
                "role": person.role,
                "aliases": person.aliases,
                "archivedAt": person.archived_at,
                "createdAt": person.created_at,
                "updatedAt": person.updated_at,
            }
        )
    return review_payload(source, ids, suggested)


@router.get("", response_model=ReviewResponse)
async def get_review(
    workspace_id: UUID, source_id: UUID, user: CurrentUser, session: Session
) -> ReviewResponse:
    return await review_payload_with_directory(
        session, await owned_meeting(session, workspace_id, source_id, user.id)
    )


@router.patch("", response_model=ReviewResponse)
async def save_review(
    workspace_id: UUID, source_id: UUID, body: ReviewPatch, user: CurrentUser, session: Session
) -> ReviewResponse:
    source = await owned_meeting(session, workspace_id, source_id, user.id, lock=True)
    if source.review_state != ReviewState.AWAITING_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting is not awaiting review")
    if source.review_revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale review revision")
    validate_unique_utterances(body.utterances)
    ids = (
        body.project_ids
        if body.project_ids is not None
        else ([body.project_id] if body.project_id is not None else [])
    )
    if (
        body.project_ids is not None
        and body.project_id is not None
        and (not ids or ids[0] != body.project_id)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "projectId must be primary")
    await validate_refs(session, workspace_id, user.id, None, body.utterances, lock=True)
    previous_ids = await project_ids(session, source)
    await replace_projects(session, source, ids, lock=True)
    if previous_ids != ids:
        source.association_revision += 1
    source.review_utterances = [
        item.model_dump(by_alias=True, mode="json") for item in body.utterances
    ]
    source.review_revision += 1
    session.add(source)
    await session.commit()
    return await review_payload_with_directory(session, source)


@router.post("/confirm", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def confirm_review(
    workspace_id: UUID, source_id: UUID, body: ConfirmRequest, user: CurrentUser, session: Session
) -> JobResponse:
    source = await owned_meeting(session, workspace_id, source_id, user.id, lock=True)
    if source.review_revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale review revision")
    if source.review_state == ReviewState.CONFIRMED:
        if source.status not in {SourceStatus.FAILED, SourceStatus.ENQUEUE_PENDING}:
            return job_payload(source)
    elif source.review_state == ReviewState.AWAITING_REVIEW:
        utterances = [ReviewUtterance.model_validate(item) for item in source.review_utterances]
        validate_unique_utterances(utterances)
        usable = [item for item in utterances if item.text]
        if not usable:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transcript text is required")
        _, people = await validate_refs(session, workspace_id, user.id, None, usable, lock=True)
        projects = []
        project_owners = {}
        for identifier in await project_ids(session, source):
            project = await active_project(session, identifier, workspace_id, user.id, lock=True)
            assert project is not None
            projects.append(project)
            if project.owner_person_id is None:
                continue
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
            project_owners[project.owner_person_id] = project_owner
        for item in usable:
            if item.person_id is not None:
                item.speaker_name = people[item.person_id].name
        source.review_utterances = [item.model_dump(by_alias=True, mode="json") for item in usable]
        source.transcript_text = "\n\n".join(f"{item.speaker_name}: {item.text}" for item in usable)
        roster: dict[UUID, WorkspacePerson] = {}
        if projects:
            members = (
                await session.exec(
                    select(ProjectMember).where(
                        ProjectMember.project_id.in_([item.id for item in projects])  # type: ignore[attr-defined]
                    )
                )
            ).all()
            for member in members:
                candidate = await session.get(
                    WorkspacePerson,
                    member.person_id,
                    with_for_update=True,
                    populate_existing=True,
                )
                if (
                    candidate is not None
                    and candidate.workspace_id == workspace_id
                    and candidate.owner_id == user.id
                    and candidate.archived_at is None
                ):
                    roster[candidate.id] = candidate
        source.confirmed_snapshot = _snapshot(projects, people, project_owners, roster)
        await session.exec(
            delete(SourcePerson).where(
                SourcePerson.source_id == source.id, SourcePerson.role == "participant"
            )
        )
        for person in people.values():
            session.add(
                SourcePerson(
                    workspace_id=workspace_id,
                    source_id=source.id,
                    person_id=person.id,
                    role="participant",
                )
            )
        source.confirmed_at = datetime.now(UTC)
        source.association_revision += 1
        source.review_state = ReviewState.CONFIRMED
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting is not awaiting review")
    source.status = SourceStatus.ENQUEUE_PENDING
    source.processing_stage = ProcessingStage.CONFIRMED
    source.error_message = None
    session.add(source)
    # Keep the source row locked through broker publication. Another confirmation
    # waits, then sees queued or failed; the worker cannot race an uncommitted gate.
    await session.flush()
    try:
        process_source.apply_async(args=[str(source.id)], task_id=str(source.id))
    except (OperationalError, ConnectionError) as exc:
        source.status = SourceStatus.FAILED
        source.error_message = "Processing queue unavailable"
        session.add(source)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Processing queue unavailable"
        ) from exc
    source.status = SourceStatus.QUEUED
    session.add(source)
    await session.commit()
    return job_payload(source)


@router.post(
    "/retry-transcription", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
async def retry_transcription(
    workspace_id: UUID, source_id: UUID, user: CurrentUser, session: Session
) -> JobResponse:
    source = await owned_meeting(session, workspace_id, source_id, user.id, lock=True)
    if source.transcript_source != "server" or source.review_state != ReviewState.TRANSCRIBING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Meeting cannot be retranscribed")
    if source.status in {
        SourceStatus.QUEUED,
        SourceStatus.ENQUEUE_PENDING,
        SourceStatus.PROCESSING,
    }:
        return job_payload(source)
    if source.status != SourceStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transcription has not failed")
    source.status = SourceStatus.ENQUEUE_PENDING
    source.processing_stage = ProcessingStage.TRANSCRIBING
    source.error_message = None
    session.add(source)
    await session.flush()
    try:
        process_source.apply_async(args=[str(source.id)], task_id=str(source.id))
    except (OperationalError, ConnectionError) as exc:
        source.status = SourceStatus.FAILED
        source.error_message = "Processing queue unavailable"
        session.add(source)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Processing queue unavailable"
        ) from exc
    source.status = SourceStatus.QUEUED
    session.add(source)
    await session.commit()
    return job_payload(source)

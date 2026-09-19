"""Owner-scoped people and project directory, separate from account membership."""

import unicodedata
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

router = APIRouter(prefix="/{workspace_id}")
Session = Annotated[AsyncSession, Depends(get_session)]


async def owned_workspace(session: AsyncSession, workspace_id: UUID, owner_id: UUID) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    return workspace


def _clean_aliases(values: list[str]) -> list[str]:
    cleaned = [item.strip() for item in values]
    if any(not item or len(item) > 120 for item in cleaned):
        raise ValueError("Aliases must be 1–120 characters")
    return list(dict.fromkeys(cleaned))


def normalize_email(value: str | None) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return None, None
    email = unicodedata.normalize("NFKC", value.strip())
    if len(email) > 320 or email.count("@") != 1 or any(char.isspace() for char in email):
        raise ValueError("Invalid email")
    local, domain = email.split("@")
    if not local or not domain or "." not in domain:
        raise ValueError("Invalid email")
    return email, email.casefold()


class PersonInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    role: str | None = Field(default=None, max_length=120)
    aliases: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str]) -> list[str]:
        return _clean_aliases(value)

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str | None) -> str | None:
        return normalize_email(value)[0]


class PersonPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    role: str | None = Field(default=None, max_length=120)
    aliases: list[str] | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Name is required")
        return value.strip() if value is not None else None

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str] | None) -> list[str] | None:
        return _clean_aliases(value) if value is not None else None

    @field_validator("role")
    @classmethod
    def clean_role(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str | None) -> str | None:
        return normalize_email(value)[0]


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID = Field(serialization_alias="workspaceId")
    name: str
    email: str | None
    role: str | None
    aliases: list[str]
    archived_at: datetime | None = Field(serialization_alias="archivedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ProjectInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=4000)
    owner_person_id: UUID | None = Field(default=None, validation_alias="ownerPersonId")
    starts_on: date | None = Field(default=None, validation_alias="startsOn")
    ends_on: date | None = Field(default=None, validation_alias="endsOn")

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()

    @model_validator(mode="after")
    def dates_in_order(self) -> "ProjectInput":
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("Project end precedes start")
        return self


class ProjectPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=4000)
    owner_person_id: UUID | None = Field(default=None, validation_alias="ownerPersonId")
    starts_on: date | None = Field(default=None, validation_alias="startsOn")
    ends_on: date | None = Field(default=None, validation_alias="endsOn")
    archived: bool | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID = Field(serialization_alias="workspaceId")
    name: str
    revision: int
    participant_ids: list[UUID] = Field(default_factory=list, serialization_alias="participantIds")
    goal: str | None
    description: str | None
    owner_person_id: UUID | None = Field(serialization_alias="ownerPersonId")
    starts_on: date | None = Field(serialization_alias="startsOn")
    ends_on: date | None = Field(serialization_alias="endsOn")
    archived_at: datetime | None = Field(serialization_alias="archivedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ProjectParticipantsPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    revision: int = Field(ge=0)
    person_ids: list[UUID] = Field(validation_alias="personIds")


async def _project_response(session: AsyncSession, project: WorkspaceProject) -> ProjectResponse:
    rows = (
        await session.exec(select(ProjectMember).where(ProjectMember.project_id == project.id))
    ).all()
    return ProjectResponse.model_validate(project).model_copy(
        update={"participant_ids": [row.person_id for row in rows]}
    )


async def active_person(
    session: AsyncSession,
    person_id: UUID | None,
    workspace_id: UUID,
    owner_id: UUID,
    *,
    lock: bool = False,
) -> WorkspacePerson | None:
    if person_id is None:
        return None
    person = await session.get(
        WorkspacePerson, person_id, with_for_update=lock, populate_existing=lock
    )
    if (
        person is None
        or person.workspace_id != workspace_id
        or person.owner_id != owner_id
        or person.archived_at is not None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid person reference")
    return person


async def active_project(
    session: AsyncSession,
    project_id: UUID | None,
    workspace_id: UUID,
    owner_id: UUID,
    *,
    lock: bool = False,
) -> WorkspaceProject | None:
    if project_id is None:
        return None
    project = await session.get(
        WorkspaceProject, project_id, with_for_update=lock, populate_existing=lock
    )
    if (
        project is None
        or project.workspace_id != workspace_id
        or project.owner_id != owner_id
        or project.archived_at is not None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid project reference")
    return project


@router.get("/people", response_model=list[PersonResponse])
async def list_people(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> list[WorkspacePerson]:
    await owned_workspace(session, workspace_id, user.id)
    return list(
        (
            await session.exec(
                select(WorkspacePerson)
                .where(
                    WorkspacePerson.workspace_id == workspace_id,
                    WorkspacePerson.owner_id == user.id,
                )
                .order_by(WorkspacePerson.name)
            )
        ).all()
    )


@router.post("/people", response_model=PersonResponse, status_code=status.HTTP_201_CREATED)
async def create_person(
    workspace_id: UUID,
    body: PersonInput,
    user: CurrentUser,
    session: Session,
    response: Response = None,
) -> WorkspacePerson:
    await owned_workspace(session, workspace_id, user.id)
    email, normalized = normalize_email(body.email)
    if normalized:
        existing = (
            await session.exec(
                select(WorkspacePerson).where(
                    WorkspacePerson.workspace_id == workspace_id,
                    WorkspacePerson.email_normalized == normalized,
                )
            )
        ).first()
        if existing is not None:
            if response is not None:
                response.status_code = status.HTTP_200_OK
            aliases = _clean_aliases([*existing.aliases, *body.aliases])
            if aliases != existing.aliases or existing.archived_at is not None:
                existing.aliases = aliases
                existing.archived_at = None
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                await session.commit()
            return existing
    person = WorkspacePerson(
        workspace_id=workspace_id,
        owner_id=user.id,
        name=body.name,
        email=email,
        email_normalized=normalized,
        role=body.role,
        aliases=body.aliases,
    )
    session.add(person)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if normalized:
            existing = (
                await session.exec(
                    select(WorkspacePerson).where(
                        WorkspacePerson.workspace_id == workspace_id,
                        WorkspacePerson.email_normalized == normalized,
                    )
                )
            ).first()
            if existing:
                if response is not None:
                    response.status_code = status.HTTP_200_OK
                existing.aliases = _clean_aliases([*existing.aliases, *body.aliases])
                existing.archived_at = None
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                await session.commit()
                return existing
        raise HTTPException(status.HTTP_409_CONFLICT, "Person email conflict") from exc
    return person


@router.patch("/people/{person_id}", response_model=PersonResponse)
async def update_person(
    workspace_id: UUID, person_id: UUID, body: PersonPatch, user: CurrentUser, session: Session
) -> WorkspacePerson:
    await owned_workspace(session, workspace_id, user.id)
    person = await session.get(WorkspacePerson, person_id)
    if person is None or person.workspace_id != workspace_id or person.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    for field in ("name", "aliases", "role", "email"):
        if field in body.model_fields_set:
            value = getattr(body, field)
            if value is None and field not in {"role", "email"}:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be null")
            setattr(person, field, value)
    if "email" in body.model_fields_set:
        person.email, person.email_normalized = normalize_email(body.email)
    if body.archived is not None:
        person.archived_at = datetime.now(UTC) if body.archived else None
    person.updated_at = datetime.now(UTC)
    session.add(person)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Person email conflict") from exc
    return person


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    workspace_id: UUID, user: CurrentUser, session: Session
) -> list[ProjectResponse]:
    await owned_workspace(session, workspace_id, user.id)
    projects = list(
        (
            await session.exec(
                select(WorkspaceProject)
                .where(
                    WorkspaceProject.workspace_id == workspace_id,
                    WorkspaceProject.owner_id == user.id,
                )
                .order_by(WorkspaceProject.name)
            )
        ).all()
    )
    return [await _project_response(session, item) for item in projects]


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: UUID, body: ProjectInput, user: CurrentUser, session: Session
) -> ProjectResponse:
    await owned_workspace(session, workspace_id, user.id)
    await active_person(session, body.owner_person_id, workspace_id, user.id, lock=True)
    project = WorkspaceProject(
        workspace_id=workspace_id,
        owner_id=user.id,
        **body.model_dump(),
    )
    session.add(project)
    await session.commit()
    return await _project_response(session, project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    workspace_id: UUID, project_id: UUID, body: ProjectPatch, user: CurrentUser, session: Session
) -> ProjectResponse:
    await owned_workspace(session, workspace_id, user.id)
    project = await session.get(
        WorkspaceProject, project_id, with_for_update=True, populate_existing=True
    )
    if project is None or project.workspace_id != workspace_id or project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    changes = body.model_dump(exclude_unset=True, exclude={"archived"})
    if "name" in changes:
        if changes["name"] is None or not changes["name"].strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
        changes["name"] = changes["name"].strip()
    if "owner_person_id" in changes:
        await active_person(session, changes["owner_person_id"], workspace_id, user.id, lock=True)
    for field, value in changes.items():
        setattr(project, field, value)
    if project.starts_on and project.ends_on and project.ends_on < project.starts_on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Project end precedes start")
    if body.archived is not None:
        project.archived_at = datetime.now(UTC) if body.archived else None
    project.updated_at = datetime.now(UTC)
    session.add(project)
    await session.commit()
    return await _project_response(session, project)


@router.get("/projects/{project_id}/participants", response_model=list[PersonResponse])
async def list_project_participants(
    workspace_id: UUID, project_id: UUID, user: CurrentUser, session: Session
) -> list[WorkspacePerson]:
    await owned_workspace(session, workspace_id, user.id)
    project = await session.get(WorkspaceProject, project_id)
    if project is None or project.workspace_id != workspace_id or project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    rows = (
        await session.exec(
            select(WorkspacePerson)
            .join(ProjectMember, ProjectMember.person_id == WorkspacePerson.id)
            .where(
                ProjectMember.project_id == project_id, WorkspacePerson.workspace_id == workspace_id
            )
            .order_by(WorkspacePerson.name)
        )
    ).all()
    return list(rows)


@router.put("/projects/{project_id}/participants", response_model=ProjectResponse)
async def replace_project_participants(
    workspace_id: UUID,
    project_id: UUID,
    body: ProjectParticipantsPatch,
    user: CurrentUser,
    session: Session,
) -> ProjectResponse:
    await owned_workspace(session, workspace_id, user.id)
    project = await session.get(
        WorkspaceProject, project_id, with_for_update=True, populate_existing=True
    )
    if project is None or project.workspace_id != workspace_id or project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if project.archived_at is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Project is archived")
    if project.revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale project revision")
    if len(body.person_ids) != len(set(body.person_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate participant")
    for person_id in body.person_ids:
        await active_person(session, person_id, workspace_id, user.id, lock=True)
    await session.exec(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    for person_id in body.person_ids:
        session.add(
            ProjectMember(workspace_id=workspace_id, project_id=project_id, person_id=person_id)
        )
    project.revision += 1
    project.updated_at = datetime.now(UTC)
    session.add(project)
    await session.commit()
    return await _project_response(session, project)

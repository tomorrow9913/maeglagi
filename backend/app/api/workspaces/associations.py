"""Explicit, owner-scoped source associations, independent of immutable review snapshots."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.directory import active_person, active_project, owned_workspace
from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.workspaces.domain.source_state import ReviewState
from app.modules.workspaces.infrastructure.models import Source, SourcePerson, SourceProject

router = APIRouter(prefix="/{workspace_id}/sources")
Session = Annotated[AsyncSession, Depends(get_session)]


class PersonAssociation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    person_id: UUID = Field(validation_alias="personId", serialization_alias="personId")
    role: Literal["participant", "author"]


class AssociationsPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    revision: int = Field(ge=0)
    project_ids: list[UUID] = Field(default_factory=list, validation_alias="projectIds")
    people: list[PersonAssociation] = Field(default_factory=list)


class AssociationsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    revision: int
    project_ids: list[UUID] = Field(serialization_alias="projectIds")
    people: list[PersonAssociation]


async def project_ids(session: AsyncSession, source: Source) -> list[UUID]:
    rows = (
        await session.exec(
            select(SourceProject)
            .where(SourceProject.source_id == source.id)
            .order_by(SourceProject.position)
        )
    ).all()
    ids = [row.project_id for row in rows]
    return ids or ([source.project_id] if source.project_id else [])


async def source_people(session: AsyncSession, source: Source) -> list[PersonAssociation]:
    rows = (
        await session.exec(select(SourcePerson).where(SourcePerson.source_id == source.id))
    ).all()
    return [PersonAssociation(person_id=row.person_id, role=row.role) for row in rows]


async def replace_projects(
    session: AsyncSession, source: Source, ids: list[UUID], *, lock: bool = False
) -> None:
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate project ID")
    for identifier in ids:
        await active_project(session, identifier, source.workspace_id, source.owner_id, lock=lock)
    await session.exec(delete(SourceProject).where(SourceProject.source_id == source.id))
    for position, identifier in enumerate(ids):
        session.add(
            SourceProject(
                workspace_id=source.workspace_id,
                source_id=source.id,
                project_id=identifier,
                position=position,
            )
        )
    source.project_id = ids[0] if ids else None
    session.add(source)


@router.get("/{source_id}/associations", response_model=AssociationsResponse)
async def get_associations(
    workspace_id: UUID, source_id: UUID, user: CurrentUser, session: Session
) -> AssociationsResponse:
    await owned_workspace(session, workspace_id, user.id)
    source = await session.get(Source, source_id)
    if source is None or source.workspace_id != workspace_id or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return AssociationsResponse(
        revision=source.association_revision,
        project_ids=await project_ids(session, source),
        people=await source_people(session, source),
    )


@router.patch("/{source_id}/associations", response_model=AssociationsResponse)
async def patch_associations(
    workspace_id: UUID,
    source_id: UUID,
    body: AssociationsPatch,
    user: CurrentUser,
    session: Session,
) -> AssociationsResponse:
    await owned_workspace(session, workspace_id, user.id)
    source = (
        await session.exec(select(Source).where(Source.id == source_id).with_for_update())
    ).first()
    if source is None or source.workspace_id != workspace_id or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    if source.association_revision != body.revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stale association revision")
    if len({(item.person_id, item.role) for item in body.people}) != len(body.people):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate person association")
    for item in body.people:
        await active_person(session, item.person_id, workspace_id, user.id, lock=True)
    await replace_projects(session, source, body.project_ids, lock=True)
    await session.exec(delete(SourcePerson).where(SourcePerson.source_id == source.id))
    for item in body.people:
        session.add(
            SourcePerson(
                workspace_id=workspace_id,
                source_id=source.id,
                person_id=item.person_id,
                role=item.role,
            )
        )
    source.association_revision += 1
    if source.kind == "meeting" and source.review_state != ReviewState.CONFIRMED:
        source.review_revision += 1
    session.add(source)
    await session.commit()
    return AssociationsResponse(
        revision=source.association_revision,
        project_ids=body.project_ids,
        people=body.people,
    )

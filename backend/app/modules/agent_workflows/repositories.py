"""Owner-scoped source reads shared by keyless workflow operations."""

from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.schemas import (
    AgentUtterance,
    SourceChunkInfo,
    SourceContent,
    SourceInfo,
    WorkspaceInfo,
)
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)


def workspace_info(workspace: Workspace) -> WorkspaceInfo:
    return WorkspaceInfo(id=workspace.id, name=workspace.name, created_at=workspace.created_at)


def source_info(source: Source) -> SourceInfo:
    stored_path = f"{source.owner_id}/{source.workspace_id}/{source.id}/"
    return SourceInfo(
        id=source.id,
        workspace_id=source.workspace_id,
        title=source.title,
        kind=source.kind,
        status=str(source.status),
        stage=str(source.processing_stage),
        analysis_mode=source.analysis_mode,
        review_state=str(source.review_state) if source.review_state else None,
        revision=source.review_revision,
        has_media=source.size_bytes > 0 and source.object_path.startswith(stored_path),
        content_type=source.content_type,
        size_bytes=source.size_bytes,
    )


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def workspace(
        self, owner_id: UUID, workspace_id: UUID, *, lock: bool = False
    ) -> Workspace:
        workspace = await self.session.get(
            Workspace, workspace_id, with_for_update=lock, populate_existing=lock
        )
        if workspace is None or workspace.owner_id != owner_id:
            raise WorkflowError("workspace_not_found", "Workspace not found", 404)
        return workspace

    async def source(
        self, owner_id: UUID, workspace_id: UUID, source_id: UUID, *, lock: bool = False
    ) -> Source:
        await self.workspace(owner_id, workspace_id, lock=lock)
        source = await self.session.get(
            Source, source_id, with_for_update=lock, populate_existing=lock
        )
        if source is None or source.owner_id != owner_id or source.workspace_id != workspace_id:
            raise WorkflowError("source_not_found", "Source not found", 404)
        return source

    async def source_content(
        self, owner_id: UUID, workspace_id: UUID, source_id: UUID
    ) -> SourceContent:
        source = await self.source(owner_id, workspace_id, source_id)
        return await self.source_content_for_source(source)

    async def source_content_for_source(self, source: Source) -> SourceContent:
        source_id = source.id
        workspace_id = source.workspace_id
        owner_id = source.owner_id
        chunks = (
            await self.session.exec(
                select(Chunk)
                .where(
                    Chunk.source_id == source_id,
                    Chunk.workspace_id == workspace_id,
                    Chunk.owner_id == owner_id,
                )
                .order_by(Chunk.position)
            )
        ).all()
        utterances = [AgentUtterance.model_validate(item) for item in source.review_utterances]
        edited_text = "\n\n".join(
            f"{item.speaker_name}: {item.text}" for item in utterances if item.text
        )
        text = (
            edited_text or source.transcript_text or source.raw_transcript_text
            if source.kind == "meeting"
            else source.content_text
        )
        return SourceContent(
            source=source_info(source),
            text=text,
            utterances=utterances,
            chunks=[
                SourceChunkInfo(
                    id=chunk.id,
                    text=chunk.content,
                    start_seconds=chunk.start_seconds,
                    end_seconds=chunk.end_seconds,
                )
                for chunk in chunks
            ],
            storage_path=source.object_path if source_info(source).has_media else None,
        )

    async def directory_snapshot(self, owner_id: UUID, workspace_id: UUID, source: Source) -> dict:
        person_ids = {
            UUID(str(item["personId"])) for item in source.review_utterances if item.get("personId")
        }
        project_ids = [
            row.project_id
            for row in (
                await self.session.exec(
                    select(SourceProject)
                    .where(
                        SourceProject.source_id == source.id,
                        SourceProject.workspace_id == workspace_id,
                    )
                    .order_by(SourceProject.position)
                )
            ).all()
        ]
        if source.project_id and source.project_id not in project_ids:
            project_ids.insert(0, source.project_id)
        people = (
            (
                await self.session.exec(
                    select(WorkspacePerson).where(
                        WorkspacePerson.id.in_(person_ids),  # type: ignore[attr-defined]
                        WorkspacePerson.workspace_id == workspace_id,
                        WorkspacePerson.owner_id == owner_id,
                        WorkspacePerson.archived_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
            if person_ids
            else []
        )
        if len(people) != len(person_ids):
            raise WorkflowError("invalid_participant", "Participant is outside workspace", 422)
        projects = (
            (
                await self.session.exec(
                    select(WorkspaceProject).where(
                        WorkspaceProject.id.in_(project_ids),  # type: ignore[attr-defined]
                        WorkspaceProject.workspace_id == workspace_id,
                        WorkspaceProject.owner_id == owner_id,
                        WorkspaceProject.archived_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
            if project_ids
            else []
        )
        if len(projects) != len(project_ids):
            raise WorkflowError("invalid_project", "Project is outside workspace", 422)
        project_by_id = {project.id: project for project in projects}
        owner_ids = {project.owner_person_id for project in projects if project.owner_person_id}
        project_owners = (
            (
                await self.session.exec(
                    select(WorkspacePerson).where(
                        WorkspacePerson.id.in_(owner_ids),  # type: ignore[attr-defined]
                        WorkspacePerson.workspace_id == workspace_id,
                        WorkspacePerson.owner_id == owner_id,
                        WorkspacePerson.archived_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
            if owner_ids
            else []
        )
        if len(project_owners) != len(owner_ids):
            raise WorkflowError("invalid_project", "Project owner is outside workspace", 422)
        owner_by_id = {person.id: person for person in project_owners}
        project_rows = [
            {
                "id": str(project.id),
                "name": project.name,
                "goal": project.goal,
                "description": project.description,
                "ownerPersonId": str(project.owner_person_id) if project.owner_person_id else None,
                "ownerName": owner_by_id[project.owner_person_id].name
                if project.owner_person_id
                else None,
                "ownerRole": owner_by_id[project.owner_person_id].role
                if project.owner_person_id
                else None,
                "startsOn": project.starts_on.isoformat() if project.starts_on else None,
                "endsOn": project.ends_on.isoformat() if project.ends_on else None,
            }
            for identifier in project_ids
            if (project := project_by_id.get(identifier)) is not None
        ]
        rows = (
            (
                await self.session.exec(
                    select(WorkspacePerson)
                    .join(ProjectMember, ProjectMember.person_id == WorkspacePerson.id)
                    .where(
                        ProjectMember.project_id.in_(project_ids),  # type: ignore[attr-defined]
                        WorkspacePerson.workspace_id == workspace_id,
                        WorkspacePerson.owner_id == owner_id,
                        WorkspacePerson.archived_at.is_(None),  # type: ignore[union-attr]
                    )
                )
            ).all()
            if project_ids
            else []
        )

        def person_row(person: WorkspacePerson) -> dict:
            return {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "email": person.email,
                "aliases": list(person.aliases),
            }

        return {
            "project": project_rows[0] if project_rows else None,
            "projects": project_rows,
            "people": [person_row(person) for person in people],
            "roster": [person_row(person) for person in {row.id: row for row in rows}.values()],
        }

    async def replace_participants(self, source: Source) -> None:
        await self.session.execute(
            delete(SourcePerson).where(
                SourcePerson.source_id == source.id,
                SourcePerson.role == "participant",
            )
        )
        identifiers = {
            UUID(str(item["personId"])) for item in source.review_utterances if item.get("personId")
        }
        for identifier in identifiers:
            self.session.add(
                SourcePerson(
                    workspace_id=source.workspace_id,
                    source_id=source.id,
                    person_id=identifier,
                    role="participant",
                )
            )

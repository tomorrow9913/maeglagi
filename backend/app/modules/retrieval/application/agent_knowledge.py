"""Owner-scoped, bounded knowledge reads shared by external interfaces."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.context_engine.application.context_store import state_from_record
from app.modules.context_engine.application.temporal import as_utc
from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord
from app.modules.retrieval.application.lexical import search_lexically
from app.modules.retrieval.infrastructure.graph_reader import GraphReader
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

MAX_PAGE = 50
MAX_OFFSET = 10_000


class KnowledgeAccessError(ValueError):
    """Stable owner or pagination error suitable for an API boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_PAGE or not 0 <= offset <= MAX_OFFSET:
        raise KnowledgeAccessError("invalid_page")
    return limit, offset


class AgentKnowledgeService:
    def __init__(self, session: AsyncSession, graph_store: Neo4jGraphStore | None = None) -> None:
        self.session = session
        self.graph_store = graph_store

    async def _owned_workspace(self, owner_id: UUID, workspace_id: UUID) -> None:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None or workspace.owner_id != owner_id:
            raise KnowledgeAccessError("workspace_not_found")

    async def lexical_search(
        self, *, owner_id: UUID, workspace_id: UUID, query: str, limit: int = 8
    ) -> list[dict]:
        await self._owned_workspace(owner_id, workspace_id)
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 8:
            raise KnowledgeAccessError("invalid_query")
        matches = await search_lexically(
            self.session,
            workspace_id=workspace_id,
            owner_id=owner_id,
            question=query,
            limit=limit,
        )
        return [
            {
                "sourceId": str(item.source_id),
                "chunkId": str(item.chunk_id) if item.chunk_id else None,
                "kind": item.kind,
                "title": item.title,
                "text": item.text,
                "timestamp": item.timestamp,
            }
            for item in matches
        ]

    async def timeline(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        limit: int = 20,
        offset: int = 0,
        kind: str | None = None,
    ) -> list[dict]:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        statement = (
            select(ContextRecord, Source)
            .join(Source, Source.id == ContextRecord.source_id)  # type: ignore[arg-type]
            .where(
                ContextRecord.workspace_id == workspace_id,
                ContextRecord.owner_id == owner_id,
                Source.workspace_id == workspace_id,
                Source.owner_id == owner_id,
            )
            .order_by(
                func.coalesce(ContextRecord.occurred_at, ContextRecord.created_at).desc(),
                ContextRecord.id,
            )
            .offset(offset)
            .limit(limit)
        )
        if kind:
            statement = statement.where(ContextRecord.kind == kind)
        rows = (await self.session.exec(statement)).all()
        keys = {str(record.metadata_["key"]) for record, _ in rows if record.metadata_.get("key")}
        replaced_by: dict[str, str] = {}
        if keys:
            successors = (
                await self.session.exec(
                    select(ContextRecord.id, ContextRecord.metadata_)
                    .where(
                        ContextRecord.workspace_id == workspace_id,
                        ContextRecord.owner_id == owner_id,
                        ContextRecord.metadata_.op("->>")("supersedes").in_(keys),
                    )
                    .order_by(ContextRecord.created_at.desc())
                    .limit(500)
                )
            ).all()
            for successor_id, metadata in successors:
                replaced_by.setdefault(str(metadata.get("supersedes")), str(successor_id))
        return [
            {
                "id": str(record.id),
                "kind": record.kind,
                "title": record.title,
                "summary": record.body[:4000],
                "summaryTruncated": len(record.body) > 4000,
                "occurredAt": (record.occurred_at or record.created_at).isoformat(),
                "sourceId": str(source.id),
                "sourceTitle": source.title,
                "chunkId": str(record.chunk_id) if record.chunk_id else None,
                "supersededBy": replaced_by.get(str(record.metadata_.get("key"))),
            }
            for record, source in rows
        ]

    async def context_store(self, *, owner_id: UUID, workspace_id: UUID) -> dict:
        """Read the current validated workspace state, distinct from the history page."""
        await self._owned_workspace(owner_id, workspace_id)
        record = (
            await self.session.exec(
                select(ContextStoreRecord).where(
                    ContextStoreRecord.workspace_id == workspace_id,
                    ContextStoreRecord.owner_id == owner_id,
                )
            )
        ).first()
        if record is None:
            return {"available": False}
        state = state_from_record(record)

        def items(values: list) -> list[dict]:
            return [
                {
                    "title": item.title[:255],
                    "description": item.description[:2000],
                    "sourceRefs": [ref[:500] for ref in item.source_refs[:10]],
                    "sourceId": item.source_id,
                    **({"decidedAt": item.decided_at} if hasattr(item, "decided_at") else {}),
                    **(
                        {"assignee": item.assignee, "dueAt": item.due_at}
                        if hasattr(item, "assignee")
                        else {}
                    ),
                }
                for item in values[:50]
            ]

        return {
            "available": True,
            "subject": state.subject[:255],
            "summary": state.summary[:4000],
            "currentState": state.current_state[:4000],
            "openIssues": items(state.open_issues),
            "decisions": items(state.decisions),
            "nextActions": items(state.next_actions),
            "sourceIds": state.source_ids[:50],
            "updatedAt": state.updated_at.isoformat() if state.updated_at else None,
            "truncated": (
                len(state.summary) > 4000
                or len(state.current_state) > 4000
                or any(
                    len(values) > 50
                    for values in (state.open_issues, state.decisions, state.next_actions)
                )
                or len(state.source_ids) > 50
            ),
        }

    async def graph_nodes(
        self, *, owner_id: UUID, workspace_id: UUID, limit: int = 20, offset: int = 0
    ) -> dict:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        if self.graph_store is None:
            return {"available": False, "nodes": [], "offset": offset, "limit": limit}
        rows = await GraphReader(self.graph_store).nodes_page(
            workspace_id, limit=limit, offset=offset
        )
        nodes = [
            {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "name": str(row["name"]),
                "sourceIds": [str(item) for item in row.get("source_ids", [])[:50]],
                "supersededBy": (str(row["superseded_by"]) if row.get("superseded_by") else None),
            }
            for row in rows
        ]
        return {"available": True, "nodes": nodes, "offset": offset, "limit": limit}

    async def graph_relations(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        at: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        if self.graph_store is None:
            return {"available": False, "relations": [], "offset": offset, "limit": limit}
        instant = as_utc(at) or datetime.now(UTC)
        rows = await GraphReader(self.graph_store).edges_page(
            workspace_id, instant, limit=limit, offset=offset
        )
        relations = [
            {
                "id": str(row["id"]) if row.get("id") else None,
                "source": str(row["source"]),
                "target": str(row["target"]),
                "kind": str(row["kind"]),
                "validFrom": row.get("valid_from"),
                "validTo": row.get("valid_to"),
            }
            for row in rows
        ]
        return {
            "available": True,
            "relations": relations,
            "offset": offset,
            "limit": limit,
        }

    async def list_people(
        self, *, owner_id: UUID, workspace_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        rows = (
            await self.session.exec(
                select(WorkspacePerson)
                .where(
                    WorkspacePerson.workspace_id == workspace_id,
                    WorkspacePerson.owner_id == owner_id,
                )
                .order_by(WorkspacePerson.name, WorkspacePerson.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "email": person.email,
                "aliases": list(person.aliases)[:20],
                "archived": person.archived_at is not None,
            }
            for person in rows
        ]

    async def list_projects(
        self, *, owner_id: UUID, workspace_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        rows = (
            await self.session.exec(
                select(WorkspaceProject)
                .where(
                    WorkspaceProject.workspace_id == workspace_id,
                    WorkspaceProject.owner_id == owner_id,
                )
                .order_by(WorkspaceProject.name, WorkspaceProject.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": str(project.id),
                "name": project.name,
                "goal": project.goal[:2000] if project.goal else None,
                "description": project.description[:2000] if project.description else None,
                "ownerPersonId": (
                    str(project.owner_person_id) if project.owner_person_id else None
                ),
                "archived": project.archived_at is not None,
            }
            for project in rows
        ]

    async def project_participants(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        limit, offset = _page(limit, offset)
        await self._owned_workspace(owner_id, workspace_id)
        project = await self.session.get(WorkspaceProject, project_id)
        if project is None or project.workspace_id != workspace_id or project.owner_id != owner_id:
            raise KnowledgeAccessError("project_not_found")
        rows = (
            await self.session.exec(
                select(WorkspacePerson)
                .join(ProjectMember, ProjectMember.person_id == WorkspacePerson.id)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.workspace_id == workspace_id,
                    WorkspacePerson.workspace_id == workspace_id,
                    WorkspacePerson.owner_id == owner_id,
                )
                .order_by(WorkspacePerson.name, WorkspacePerson.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": str(person.id),
                "name": person.name,
                "role": person.role,
                "email": person.email,
                "archived": person.archived_at is not None,
            }
            for person in rows
        ]

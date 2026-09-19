from collections import Counter
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.workspaces.schemas import (
    GraphEdgeResponse,
    GraphNodeResponse,
    GraphSourceResponse,
    KnowledgeGraphResponse,
)
from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.modules.context_engine.application.entity_resolution import entity_id
from app.modules.context_engine.application.temporal import as_utc
from app.modules.retrieval.infrastructure.graph_reader import GraphReader
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.domain.source_state import ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

router = APIRouter(prefix="/workspaces")
Session = Annotated[AsyncSession, Depends(get_session)]

# The frontend draws five entity types; the ontology has ten. `kind` carries the exact one.
ENTITY_TYPE = {
    "Person": "person",
    "Organization": "person",
    "Project": "project",
    "Technology": "project",
    "Decision": "decision",
    "Task": "task",
    "Meeting": "event",
    "Event": "event",
    "Issue": "event",
    "Document": "event",
}
RELATION_TYPE = {
    "PARTICIPATED_IN": "participates_in",
    "DECIDED_IN": "decided",
    "ASSIGNED_TO": "assigned_to",
    "BLOCKED_BY": "blocks",
    "WORKS_ON": "relates_to",
    "CREATED": "relates_to",
    "RELATED_TO": "relates_to",
    "MENTIONED_IN": "relates_to",
}


async def get_graph_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[Neo4jGraphStore | None]:
    if not settings.neo4j_enabled:
        yield None
        return
    store = Neo4jGraphStore.from_settings(settings)
    try:
        yield store
    finally:
        await store.close()


GraphStore = Annotated[Neo4jGraphStore | None, Depends(get_graph_store)]


def _edge(row: dict[str, Any]) -> GraphEdgeResponse:
    source, target, kind = str(row["source"]), str(row["target"]), row["kind"]
    if kind == "BLOCKED_BY":  # "A blocked by B" is drawn as "B blocks A"
        source, target = target, source
    return GraphEdgeResponse(
        id=str(row["id"]) if row.get("id") else f"{source}-{kind}-{target}",
        source=source,
        target=target,
        type=RELATION_TYPE.get(kind, "relates_to"),
        kind=kind,
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
    )


@router.get("/{workspace_id}/graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(
    workspace_id: UUID,
    user: CurrentUser,
    session: Session,
    store: GraphStore,
    at: Annotated[
        datetime | None,
        Query(description="Show relations valid at this instant (ISO 8601). Defaults to now."),
    ] = None,
    include_materials: Annotated[bool, Query(alias="includeMaterials")] = True,
) -> KnowledgeGraphResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    instant = as_utc(at) or datetime.now(UTC)

    reader = GraphReader(store) if store is not None else None
    rows = await reader.nodes(workspace_id) if reader else []
    node_ids = {str(row["id"]) for row in rows}
    edges = [
        edge
        for edge in (
            _edge(row) for row in (await reader.edges(workspace_id, instant) if reader else [])
        )
        if edge.source in node_ids and edge.target in node_ids
    ]
    # A replaced decision points at its successor: draw "new supersedes old".
    for row in rows:
        successor = str(row["superseded_by"]) if row.get("superseded_by") else None
        if successor in node_ids:
            edges.append(
                GraphEdgeResponse(
                    id=f"{successor}-supersedes-{row['id']}",
                    source=successor,
                    target=str(row["id"]),
                    type="supersedes",
                    kind="SUPERSEDES",
                )
            )

    wanted = {
        UUID(str(identifier)) for row in rows for identifier in row["source_ids"] if identifier
    }
    sources: dict[str, Source] = {}
    if wanted:
        found = await session.exec(
            select(Source).where(
                Source.id.in_(wanted),  # type: ignore[attr-defined]
                Source.workspace_id == workspace.id,
                Source.owner_id == user.id,
            )
        )
        sources = {str(source.id): source for source in found.all()}

    nodes = [
        GraphNodeResponse(
            id=str(row["id"]),
            type=ENTITY_TYPE.get(row["kind"], "event"),
            kind=row["kind"],
            label=row["name"],
            degree=0,
            sources=[
                GraphSourceResponse(
                    id=sources[str(i)].id, kind=sources[str(i)].kind, title=sources[str(i)].title
                )
                for i in row["source_ids"]
                if str(i) in sources
            ],
            superseded_by=str(row["superseded_by"]) if row.get("superseded_by") else None,
        )
        for row in rows
    ]
    directory_ids: dict[tuple[str, UUID], str] = {}
    for row in rows:
        for identifier in row.get("identifiers", []):
            for kind in ("person", "project"):
                prefix = f"directory:{kind}:"
                if identifier.startswith(prefix):
                    with suppress(ValueError):
                        directory_ids[(kind, UUID(identifier.removeprefix(prefix)))] = str(
                            row["id"]
                        )
    people = (
        await session.exec(
            select(WorkspacePerson).where(
                WorkspacePerson.workspace_id == workspace_id, WorkspacePerson.owner_id == user.id
            )
        )
    ).all()
    projects = (
        await session.exec(
            select(WorkspaceProject).where(
                WorkspaceProject.workspace_id == workspace_id, WorkspaceProject.owner_id == user.id
            )
        )
    ).all()
    existing = {node.id for node in nodes}

    def add_directory(kind: str, identifier: UUID, label: str) -> str:
        node_id = directory_ids.get((kind.lower(), identifier)) or str(
            entity_id(workspace_id, kind, f"id:directory:{kind.lower()}:{identifier}")
        )
        if node_id in existing:
            nodes[:] = [
                node.model_copy(
                    update={
                        "label": label,
                        "directory_id": identifier,
                        "directory_kind": kind,
                    }
                )
                if node.id == node_id
                else node
                for node in nodes
            ]
        else:
            nodes.append(
                GraphNodeResponse(
                    id=node_id,
                    type=kind.lower(),
                    kind=kind,
                    label=label,
                    degree=0,
                    sources=[],
                    directory_id=identifier,
                    directory_kind=kind,
                )
            )
            existing.add(node_id)
        return node_id

    person_nodes = {person.id: add_directory("Person", person.id, person.name) for person in people}
    project_nodes = {
        project.id: add_directory("Project", project.id, project.name) for project in projects
    }

    def explicit_edge(source: str, target: str, kind: str, role: str) -> GraphEdgeResponse:
        return GraphEdgeResponse(
            id=str(
                uuid5(NAMESPACE_URL, f"explicit:{workspace_id}:{source}:{kind}:{target}:{role}")
            ),
            source=source,
            target=target,
            kind=kind,
            type=RELATION_TYPE.get(kind, "relates_to"),
            explicit=True,
            role=role,
        )

    membership = (
        await session.exec(select(ProjectMember).where(ProjectMember.workspace_id == workspace_id))
    ).all()
    for item in membership:
        if item.person_id in person_nodes and item.project_id in project_nodes:
            edges.append(
                explicit_edge(
                    person_nodes[item.person_id],
                    project_nodes[item.project_id],
                    "WORKS_ON",
                    "member",
                )
            )
    if include_materials:
        material_sources = (
            await session.exec(
                select(Source).where(
                    Source.workspace_id == workspace_id, Source.owner_id == user.id
                )
            )
        ).all()
        visible = {
            source.id: source
            for source in material_sources
            if source.status == SourceStatus.SUCCEEDED
            or (source.kind == "meeting" and source.review_state == ReviewState.CONFIRMED)
        }
        source_projects = (
            await session.exec(
                select(SourceProject).where(SourceProject.workspace_id == workspace_id)
            )
        ).all()
        source_people = (
            await session.exec(
                select(SourcePerson).where(SourcePerson.workspace_id == workspace_id)
            )
        ).all()
        for source in visible.values():
            node_id = str(
                entity_id(
                    workspace_id,
                    "Meeting" if source.kind == "meeting" else "Document",
                    f"source:{source.id}",
                )
            )
            nodes.append(
                GraphNodeResponse(
                    id=node_id,
                    type="event",
                    kind="Meeting" if source.kind == "meeting" else "Document",
                    label=source.title,
                    degree=0,
                    sources=[
                        GraphSourceResponse(id=source.id, kind=source.kind, title=source.title)
                    ],
                    material=True,
                    source_id=source.id,
                )
            )
            for row in rows:
                if row["kind"] not in {"Event", "Decision", "Task", "Issue", "Technology"}:
                    continue
                if str(source.id) not in {str(item) for item in row.get("source_ids", [])}:
                    continue
                extracted_id = str(row["id"])
                edges.append(
                    GraphEdgeResponse(
                        id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"evidence:{workspace_id}:{extracted_id}:{source.id}",
                            )
                        ),
                        source=extracted_id,
                        target=node_id,
                        kind="MENTIONED_IN",
                        type="relates_to",
                    )
                )
            for item in source_projects:
                if item.source_id == source.id and item.project_id in project_nodes:
                    edges.append(
                        explicit_edge(
                            node_id, project_nodes[item.project_id], "RELATED_TO", "project"
                        )
                    )
            if (
                source.project_id
                and not any(item.source_id == source.id for item in source_projects)
                and source.project_id in project_nodes
            ):
                edges.append(
                    explicit_edge(
                        node_id, project_nodes[source.project_id], "RELATED_TO", "project"
                    )
                )
            for item in source_people:
                if item.source_id == source.id and item.person_id in person_nodes:
                    kind = "CREATED" if item.role == "author" else "PARTICIPATED_IN"
                    edges.append(
                        explicit_edge(person_nodes[item.person_id], node_id, kind, item.role)
                    )
    degree = Counter(edge.source for edge in edges) + Counter(edge.target for edge in edges)
    nodes = [node.model_copy(update={"degree": degree[node.id]}) for node in nodes]
    return KnowledgeGraphResponse(nodes=nodes, edges=edges)

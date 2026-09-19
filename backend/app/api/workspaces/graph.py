from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

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
from app.modules.context_engine.application.temporal import as_utc
from app.modules.retrieval.infrastructure.graph_reader import GraphReader
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.infrastructure.models import Source, Workspace

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
}


async def get_graph_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[Neo4jGraphStore]:
    if not settings.neo4j_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Graph store is not configured")
    store = Neo4jGraphStore.from_settings(settings)
    try:
        yield store
    finally:
        await store.close()


GraphStore = Annotated[Neo4jGraphStore, Depends(get_graph_store)]


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
) -> KnowledgeGraphResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    instant = as_utc(at) or datetime.now(UTC)

    reader = GraphReader(store)
    rows = await reader.nodes(workspace_id)
    node_ids = {str(row["id"]) for row in rows}
    edges = [
        edge
        for edge in (_edge(row) for row in await reader.edges(workspace_id, instant))
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

    degree = Counter(edge.source for edge in edges) + Counter(edge.target for edge in edges)
    nodes = [
        GraphNodeResponse(
            id=str(row["id"]),
            type=ENTITY_TYPE.get(row["kind"], "event"),
            kind=row["kind"],
            label=row["name"],
            degree=degree[str(row["id"])],
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
    return KnowledgeGraphResponse(nodes=nodes, edges=edges)

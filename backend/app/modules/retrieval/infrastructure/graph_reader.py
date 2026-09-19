from datetime import datetime
from typing import Any
from uuid import UUID

import sentry_sdk

from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

_NODES = """
MATCH (e:Entity {workspace_id: $workspace_id})
RETURN e.id AS id, e.kind AS kind, e.name AS name,
       coalesce(e.source_ids, []) AS source_ids, e.superseded_by AS superseded_by,
       coalesce(e.identifiers, []) AS identifiers
ORDER BY e.name, e.id
"""

# Relations without a stated start or end count as open, so legacy edges stay visible.
_EDGES = """
MATCH (a:Entity {workspace_id: $workspace_id})-[r]->(b:Entity {workspace_id: $workspace_id})
WHERE type(r) IN $kinds
  AND (r.valid_from IS NULL OR r.valid_from <= datetime($at))
  AND (r.valid_to IS NULL OR r.valid_to >= datetime($at))
RETURN r.id AS id, a.id AS source, b.id AS target, type(r) AS kind,
       toString(r.valid_from) AS valid_from, toString(r.valid_to) AS valid_to
ORDER BY a.name, a.id, kind, b.name, b.id, r.id, elementId(r)
"""


class GraphReader:
    """Reads a workspace's knowledge graph as plain rows for the API layer to shape."""

    def __init__(self, store: Neo4jGraphStore) -> None:
        self.store = store

    async def nodes(self, workspace_id: UUID) -> list[dict[str, Any]]:
        with sentry_sdk.start_span(op="db.neo4j.query", name="graph.nodes"):
            return await self.store.execute(_NODES, {"workspace_id": str(workspace_id)})

    async def nodes_page(
        self, workspace_id: UUID, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Return a bounded page of graph nodes for external read clients."""
        with sentry_sdk.start_span(op="db.neo4j.query", name="graph.nodes_page"):
            return await self.store.execute(
                _NODES + "\nSKIP $offset LIMIT $limit",
                {"workspace_id": str(workspace_id), "offset": offset, "limit": limit},
            )

    async def edges(self, workspace_id: UUID, at: datetime) -> list[dict[str, Any]]:
        """Relations that were valid at `at` (timezone-aware)."""
        with sentry_sdk.start_span(op="db.neo4j.query", name="graph.edges"):
            return await self.store.execute(
                _EDGES,
                {
                    "workspace_id": str(workspace_id),
                    "at": at.isoformat(),
                    "kinds": [kind.value for kind in RelationKind],
                },
            )

    async def edges_page(
        self, workspace_id: UUID, at: datetime, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Return a bounded page of relations valid at a chosen instant."""
        with sentry_sdk.start_span(op="db.neo4j.query", name="graph.edges_page"):
            return await self.store.execute(
                _EDGES + "\nSKIP $offset LIMIT $limit",
                {
                    "workspace_id": str(workspace_id),
                    "at": at.isoformat(),
                    "kinds": [kind.value for kind in RelationKind],
                    "offset": offset,
                    "limit": limit,
                },
            )

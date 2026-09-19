from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

_ENTITIES = """
MATCH (e:Entity {workspace_id: $workspace_id})
RETURN e.name AS name, e.kind AS kind, coalesce(e.keys, []) AS keys,
       coalesce(e.source_ids, []) AS source_ids, e.superseded_by IS NOT NULL AS superseded
"""

# Two hops out from the entities the question names (person -> project -> meeting -> decision),
# over relations that were valid at `at`.
_FACTS = """
MATCH (seed:Entity {workspace_id: $workspace_id})
WHERE any(key IN $keys WHERE key IN coalesce(seed.keys, []))
MATCH p = (seed)-[*1..2]-(n:Entity {workspace_id: $workspace_id})
WITH DISTINCT relationships(p) AS rels
UNWIND rels AS r
WITH DISTINCT r
WHERE type(r) IN $kinds
  AND (r.valid_from IS NULL OR r.valid_from <= datetime($at))
  AND (r.valid_to IS NULL OR r.valid_to >= datetime($at))
WITH r, startNode(r) AS a, endNode(r) AS b
RETURN a.name AS source, a.kind AS source_kind, type(r) AS kind,
       b.name AS target, b.kind AS target_kind,
       coalesce(a.source_ids, []) + coalesce(b.source_ids, []) AS source_ids,
       [x IN [a, b] WHERE x.superseded_by IS NOT NULL | x.name] AS superseded
LIMIT $limit
"""


class GraphNeighborhood:
    """Reads what the graph knows around the entities a question mentions."""

    def __init__(self, store: Neo4jGraphStore) -> None:
        self.store = store

    async def entities(self, workspace_id: UUID) -> list[dict[str, Any]]:
        return await self.store.execute(_ENTITIES, {"workspace_id": str(workspace_id)})

    async def facts(
        self, workspace_id: UUID, keys: list[str], at: datetime, limit: int = 40
    ) -> list[dict[str, Any]]:
        return await self.store.execute(
            _FACTS,
            {
                "workspace_id": str(workspace_id),
                "keys": keys,
                "at": at.isoformat(),
                "kinds": [kind.value for kind in RelationKind],
                "limit": limit,
            },
        )

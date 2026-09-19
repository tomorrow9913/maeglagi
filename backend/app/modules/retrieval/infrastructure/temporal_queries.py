"""Read side of Temporal processing: what was decided, what replaced it, what held at a time.

This is what separates the graph from plain RAG: an answer can say a decision is no longer
current and cite the decision that replaced it.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.context_engine.application.temporal import as_utc, parse_instant
from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

_DECISION_HISTORY = """
MATCH (d:Entity {workspace_id: $workspace_id, kind: 'Decision'})
OPTIONAL MATCH (n:Entity {id: d.superseded_by, workspace_id: $workspace_id})
RETURN d.id AS id, d.name AS name, d.timestamp AS decided_at,
       d.superseded_by AS superseded_by, n.name AS superseded_by_name
ORDER BY d.timestamp IS NULL, d.timestamp
"""

_RELATIONS_AS_OF = """
MATCH (a:Entity {workspace_id: $workspace_id})-[r]->(b:Entity {workspace_id: $workspace_id})
WHERE type(r) IN $kinds
  AND (r.valid_from IS NULL OR r.valid_from <= datetime($at))
  AND (r.valid_to IS NULL OR r.valid_to >= datetime($at))
RETURN a.name AS source, type(r) AS kind, b.name AS target,
       toString(r.valid_from) AS valid_from, toString(r.valid_to) AS valid_to
ORDER BY a.name, kind, b.name
"""


class DecisionRecord(BaseModel):
    id: UUID
    name: str
    decided_at: datetime | None
    superseded_by: UUID | None
    superseded_by_name: str | None

    @property
    def is_current(self) -> bool:
        return self.superseded_by is None


class ValidRelation(BaseModel):
    source: str
    kind: str
    target: str
    valid_from: datetime | None
    valid_to: datetime | None


class TemporalQueries:
    def __init__(self, store: Neo4jGraphStore) -> None:
        self.store = store

    async def decision_history(self, workspace_id: UUID) -> list[DecisionRecord]:
        """Every decision oldest first, each pointing at the decision that replaced it."""
        records = await self.store.execute(_DECISION_HISTORY, {"workspace_id": str(workspace_id)})
        return [
            DecisionRecord(
                id=UUID(record["id"]),
                name=record["name"],
                decided_at=parse_instant(record["decided_at"]),
                superseded_by=UUID(record["superseded_by"]) if record["superseded_by"] else None,
                superseded_by_name=record["superseded_by_name"],
            )
            for record in records
        ]

    async def current_decisions(self, workspace_id: UUID) -> list[DecisionRecord]:
        return [d for d in await self.decision_history(workspace_id) if d.is_current]

    async def relations_as_of(self, workspace_id: UUID, at: datetime) -> list[ValidRelation]:
        """Relations that held at `at`. Unknown start / no stated end count as open."""
        instant = as_utc(at)
        assert instant is not None
        records = await self.store.execute(
            _RELATIONS_AS_OF,
            {
                "workspace_id": str(workspace_id),
                "at": instant.isoformat(),
                "kinds": [kind.value for kind in RelationKind],
            },
        )
        return [
            ValidRelation(
                source=r["source"],
                kind=r["kind"],
                target=r["target"],
                valid_from=parse_instant(r["valid_from"]),
                valid_to=parse_instant(r["valid_to"]),
            )
            for r in records
        ]

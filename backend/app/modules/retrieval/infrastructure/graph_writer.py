from collections import defaultdict
from typing import Any
from uuid import UUID

from app.modules.context_engine.application.entity_resolution import (
    ResolvedGraph,
    pick_canonical,
    relation_id,
)
from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.retrieval.domain.models import GraphEntity, GraphRelation
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

_FIND_EXISTING = """
UNWIND $rows AS row
MATCH (e:Entity {workspace_id: $workspace_id})
WHERE e.kind = row.kind AND (
    any(key IN row.keys WHERE key IN coalesce(e.keys, []))
    OR any(ident IN row.identifiers WHERE ident IN coalesce(e.identifiers, []))
)
RETURN row.id AS row_id, e.id AS id, e.name AS name, e.aliases AS aliases,
       e.keys AS keys, e.identifiers AS identifiers, e.source_ids AS source_ids
"""

_UPSERT_ENTITIES = """
UNWIND $rows AS row
MERGE (e:Entity {id: row.id})
SET e.workspace_id = row.workspace_id, e.kind = row.kind, e.name = row.name,
    e.aliases = row.aliases, e.keys = row.keys, e.identifiers = row.identifiers,
    e.source_ids = row.source_ids,
    e.source_id = row.source_id, e.chunk_id = row.chunk_id, e.timestamp = row.timestamp
"""

# Neo4j cannot parameterize relationship types. `kind` only ever comes from RelationKind.
_UPSERT_RELATIONS = """
UNWIND $rows AS row
MATCH (a:Entity {{id: row.source_entity_id, workspace_id: row.workspace_id}})
MATCH (b:Entity {{id: row.target_entity_id, workspace_id: row.workspace_id}})
MERGE (a)-[r:{kind}]->(b)
ON CREATE SET r.id = row.id
SET r.workspace_id = row.workspace_id, r.source_id = row.source_id,
    r.chunk_id = row.chunk_id, r.timestamp = row.timestamp
"""


class GraphWriter:
    """Idempotent Entity/Relation upsert; merges into nodes other sources already created."""

    def __init__(self, store: Neo4jGraphStore) -> None:
        self.store = store

    async def write(self, graph: ResolvedGraph) -> list[str]:
        """Upsert the graph and return warnings about matches it refused to guess."""
        if not graph.entities:
            return []
        merged, id_map, warnings = await self._reconcile(graph.entities)
        await self.store.execute(
            _UPSERT_ENTITIES,
            {"rows": [_entity_row(entity, sources) for entity, sources in merged]},
        )
        for kind, relations in _group_by_kind(graph.relations, id_map).items():
            await self.store.execute(
                _UPSERT_RELATIONS.format(kind=kind.value),
                {"rows": [_relation_row(r) for r in relations]},
            )
        return warnings

    async def _reconcile(
        self, entities: list[GraphEntity]
    ) -> tuple[list[tuple[GraphEntity, list[str]]], dict[UUID, UUID], list[str]]:
        """Point each entity at the existing node it is the same as, without guessing.

        Shared identifier -> same node. Shared name only -> same node unless both carry
        identifiers that differ (homonyms). Several equally plausible same-name nodes and no
        identifier to tell them apart -> keep separate and warn.
        """
        workspace_id = entities[0].workspace_id
        records = await self.store.execute(
            _FIND_EXISTING,
            {
                "workspace_id": str(workspace_id),
                "rows": [
                    {"id": str(e.id), "kind": e.kind, "keys": e.keys, "identifiers": e.identifiers}
                    for e in entities
                ],
            },
        )
        matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            matches[record["row_id"]].append(record)

        warnings: list[str] = []
        merged: dict[UUID, tuple[GraphEntity, set[str]]] = {}
        id_map: dict[UUID, UUID] = {}
        for entity in entities:
            own = set(entity.identifiers)
            found = matches.get(str(entity.id), [])
            strong = [r for r in found if own & set(r.get("identifiers") or [])]
            weak = [
                r
                for r in found
                if r not in strong
                and not (own and r.get("identifiers"))  # both identified => homonym
            ]
            chosen: list[dict[str, Any]]
            if strong:
                chosen = strong
            elif not own and sum(1 for r in weak if r.get("identifiers")) > 1:
                warnings.append(
                    f"이름이 같은 기존 노드가 여러 개라 합치지 않았습니다: {entity.name} "
                    "(이메일 등 식별 정보가 필요합니다)"
                )
                chosen = []
            else:
                chosen = weak
            target_id = UUID(min(r["id"] for r in chosen)) if chosen else entity.id
            claimed = merged.get(target_id)
            if claimed is not None and target_id != entity.id:
                # Another extracted entity already took this node; identified people who
                # disagree must not both fold into it.
                taken = set(claimed[0].identifiers)
                if own and taken and own.isdisjoint(taken):
                    target_id, chosen, claimed = entity.id, [], merged.get(entity.id)
            id_map[entity.id] = target_id
            names = [entity.name, *entity.aliases]
            keys = set(entity.keys)
            identifiers = set(own)
            sources = {str(entity.evidence.source_id)}
            for record in chosen:
                if UUID(record["id"]) == target_id:
                    names += [record["name"], *(record["aliases"] or [])]
                    keys |= set(record["keys"] or [])
                    identifiers |= set(record.get("identifiers") or [])
                    sources |= set(record["source_ids"] or [])
            if claimed is not None:  # two extracted entities collapsed onto one node
                previous, previous_sources = claimed
                names += [previous.name, *previous.aliases]
                keys |= set(previous.keys)
                identifiers |= set(previous.identifiers)
                sources |= previous_sources
            name = pick_canonical(names, entity.kind)
            merged[target_id] = (
                entity.model_copy(
                    update={
                        "id": target_id,
                        "name": name,
                        "aliases": [n for n in dict.fromkeys(names) if n != name],
                        "keys": sorted(keys),
                        "identifiers": sorted(identifiers),
                    }
                ),
                sources,
            )
        merged_list = [(entity, sorted(sources)) for entity, sources in merged.values()]
        return merged_list, id_map, warnings


def _entity_row(entity: GraphEntity, source_ids: list[str]) -> dict[str, Any]:
    return {
        "id": str(entity.id),
        "workspace_id": str(entity.workspace_id),
        "kind": entity.kind,
        "name": entity.name,
        "aliases": entity.aliases,
        "keys": entity.keys,
        "identifiers": entity.identifiers,
        "source_ids": source_ids,
        "source_id": str(entity.evidence.source_id),
        "chunk_id": str(entity.evidence.chunk_id) if entity.evidence.chunk_id else None,
        "timestamp": entity.evidence.timestamp.isoformat() if entity.evidence.timestamp else None,
    }


def _relation_row(relation: GraphRelation) -> dict[str, Any]:
    return {
        "id": str(relation.id),
        "workspace_id": str(relation.workspace_id),
        "source_entity_id": str(relation.source_entity_id),
        "target_entity_id": str(relation.target_entity_id),
        "source_id": str(relation.evidence.source_id),
        "chunk_id": str(relation.evidence.chunk_id) if relation.evidence.chunk_id else None,
        "timestamp": relation.evidence.timestamp.isoformat()
        if relation.evidence.timestamp
        else None,
    }


def _group_by_kind(
    relations: list[GraphRelation], id_map: dict[UUID, UUID]
) -> dict[RelationKind, list[GraphRelation]]:
    grouped: dict[RelationKind, dict[UUID, GraphRelation]] = defaultdict(dict)
    for relation in relations:
        source = id_map.get(relation.source_entity_id, relation.source_entity_id)
        target = id_map.get(relation.target_entity_id, relation.target_entity_id)
        kind = RelationKind(relation.kind)  # raises for anything outside the ontology
        identifier = relation_id(relation.workspace_id, source, target, kind.value)
        grouped[kind][identifier] = relation.model_copy(
            update={"id": identifier, "source_entity_id": source, "target_entity_id": target}
        )
    return {kind: list(items.values()) for kind, items in grouped.items()}

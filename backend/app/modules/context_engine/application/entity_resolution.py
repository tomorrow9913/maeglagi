import re
import unicodedata
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import EntityKind
from app.modules.retrieval.domain.models import GraphEntity, GraphEvidence, GraphRelation

_SEPARATORS = re.compile(r"[\s·.,_\-]+")
_PERSON_HONORIFICS = ("님", "씨")


class ResolvedGraph(BaseModel):
    entities: list[GraphEntity]
    relations: list[GraphRelation]
    warnings: list[str]


def normalize_name(name: str, kind: str) -> str:
    """Spelling-insensitive key: NFKC, case, spacing/punctuation, Korean person honorifics."""
    text = _SEPARATORS.sub("", unicodedata.normalize("NFKC", name).casefold())
    if kind == EntityKind.PERSON.value:
        for honorific in _PERSON_HONORIFICS:
            if text.endswith(honorific) and len(text) > len(honorific) + 1:
                return text[: -len(honorific)]
    return text


def pick_canonical(names: list[str], kind: str) -> str:
    """Most complete spelling (longest normalized form); ties go to the cleanest raw text."""
    return max(dict.fromkeys(names), key=lambda n: (len(normalize_name(n, kind)), -len(n)))


def entity_id(workspace_id: UUID, kind: str, key: str) -> UUID:
    """Deterministic id so re-running the same source upserts instead of duplicating."""
    return uuid5(NAMESPACE_URL, f"maeglagi:{workspace_id}:{kind}:{key}")


def relation_id(workspace_id: UUID, source: UUID, target: UUID, kind: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"maeglagi:{workspace_id}:{source}:{kind}:{target}")


class _Group:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.names: list[str] = []
        self.keys: set[str] = set()
        self.timestamp: datetime | None = None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def resolve_extraction(
    result: ExtractionResult,
    *,
    workspace_id: UUID,
    source_id: UUID,
    chunk_id: UUID | None = None,
    timestamp: datetime | None = None,
) -> ResolvedGraph:
    """Merge same-kind entities that share a normalized name or alias, then wire relations.

    Events (Meeting/Decision/Task/...) are graph entities too, so both lists are resolved together.
    """
    warnings: list[str] = []
    mentions: list[tuple[str, str, list[str], datetime | None]] = [
        (item.name, item.kind.value, item.aliases, None) for item in result.entities
    ] + [(item.name, item.kind.value, [], _parse_time(item.occurred_at)) for item in result.events]

    groups: list[_Group] = []
    key_to_group: dict[tuple[str, str], _Group] = {}
    for name, kind, aliases, occurred_at in mentions:
        keys = {normalize_name(value, kind) for value in [name, *aliases]}
        keys.discard("")
        if not keys:
            warnings.append(f"이름이 비어 있는 개체를 버렸습니다: {name!r}")
            continue
        matched = {
            id(key_to_group[(kind, key)]): key_to_group[(kind, key)]
            for key in keys
            if (kind, key) in key_to_group
        }
        if matched:
            group, *others = matched.values()
            for other in others:  # this mention bridges two groups: fold them together
                group.names += other.names
                group.keys |= other.keys
                group.timestamp = group.timestamp or other.timestamp
                groups.remove(other)
        else:
            group = _Group(kind)
            groups.append(group)
        group.names += [name, *aliases]
        group.keys |= keys
        group.timestamp = group.timestamp or occurred_at
        for key in group.keys:
            key_to_group[(kind, key)] = group

    entities: list[GraphEntity] = []
    lookup: dict[str, UUID] = {}
    for group in groups:
        canonical = pick_canonical(group.names, group.kind)
        key = normalize_name(canonical, group.kind)
        identifier = entity_id(workspace_id, group.kind, key)
        entities.append(
            GraphEntity(
                id=identifier,
                workspace_id=workspace_id,
                kind=group.kind,
                name=canonical,
                aliases=[name for name in dict.fromkeys(group.names) if name != canonical],
                keys=sorted(group.keys),
                evidence=GraphEvidence(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    timestamp=group.timestamp or timestamp,
                ),
            )
        )
        for group_key in group.keys:
            lookup[f"{group.kind}:{group_key}"] = identifier

    def endpoint(name: str) -> UUID | None:
        # Relation stage refers to entities by name only, so match across kinds.
        for kind in EntityKind:
            found = lookup.get(f"{kind.value}:{normalize_name(name, kind.value)}")
            if found:
                return found
        return None

    relations: dict[UUID, GraphRelation] = {}
    for relation in result.relations:
        source, target = endpoint(relation.source), endpoint(relation.target)
        if source is None or target is None:
            warnings.append(
                f"병합 후 개체를 찾지 못한 관계를 버렸습니다: {relation.source} → {relation.target}"
            )
            continue
        identifier = relation_id(workspace_id, source, target, relation.kind.value)
        relations[identifier] = GraphRelation(
            id=identifier,
            workspace_id=workspace_id,
            source_entity_id=source,
            target_entity_id=target,
            kind=relation.kind.value,
            evidence=GraphEvidence(source_id=source_id, chunk_id=chunk_id, timestamp=timestamp),
        )
    return ResolvedGraph(entities=entities, relations=list(relations.values()), warnings=warnings)

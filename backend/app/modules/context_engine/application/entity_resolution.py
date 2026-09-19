import re
import unicodedata
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from app.modules.context_engine.application.temporal import (
    Interval,
    as_utc,
    normalize,
    parse_instant,
)
from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import EntityKind
from app.modules.retrieval.domain.models import GraphEntity, GraphEvidence, GraphRelation

_SEPARATORS = re.compile(r"[\s·.,_\-]+")
_PERSON_HONORIFICS = ("님", "씨")


class Supersession(BaseModel):
    """A new decision that replaces an earlier one this extraction could not find itself."""

    new_id: UUID
    old_name: str
    old_keys: list[str]


class ResolvedGraph(BaseModel):
    entities: list[GraphEntity]
    relations: list[GraphRelation]
    warnings: list[str]
    # Replaced decisions that live in the graph already; GraphWriter links them up.
    supersessions: list[Supersession] = []


def normalize_name(name: str, kind: str) -> str:
    """Spelling-insensitive key: NFKC, case, spacing/punctuation, Korean person honorifics."""
    text = _SEPARATORS.sub("", unicodedata.normalize("NFKC", name).casefold())
    if kind == EntityKind.PERSON.value:
        for honorific in _PERSON_HONORIFICS:
            if text.endswith(honorific) and len(text) > len(honorific) + 1:
                return text[: -len(honorific)]
    return text


def normalize_identifier(value: str) -> str:
    """Emails compare case-insensitively and without a mailto: prefix; others just by text."""
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    return text.removeprefix("mailto:").strip()


def pick_canonical(names: list[str], kind: str) -> str:
    """Most complete spelling (longest normalized form); ties go to the cleanest raw text."""
    return max(dict.fromkeys(names), key=lambda n: (len(normalize_name(n, kind)), -len(n)))


def entity_id(workspace_id: UUID, kind: str, key: str) -> UUID:
    """Deterministic id so re-running the same source upserts instead of duplicating."""
    return uuid5(NAMESPACE_URL, f"maeglagi:{workspace_id}:{kind}:{key}")


def relation_id(
    workspace_id: UUID,
    source: UUID,
    target: UUID,
    kind: str,
    valid_from: datetime | None = None,
) -> UUID:
    """One id per relation *interval*: the same triple can hold several disjoint periods."""
    start = valid_from.isoformat() if valid_from else ""
    return uuid5(NAMESPACE_URL, f"maeglagi:{workspace_id}:{source}:{kind}:{target}:{start}")


class _Group:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.names: list[str] = []
        self.keys: set[str] = set()
        self.identifiers: set[str] = set()
        self.timestamp: datetime | None = None

    def absorb(self, other: "_Group") -> None:
        self.names += other.names
        self.keys |= other.keys
        self.identifiers |= other.identifiers
        self.timestamp = self.timestamp or other.timestamp


def _stable_key(group_kind: str, canonical: str, identifiers: set[str]) -> str:
    # Identified entities are keyed by identifier, so homonyms never share a node id.
    directory_ids = sorted(value for value in identifiers if value.startswith("directory:"))
    if directory_ids:
        return f"id:{directory_ids[0]}"
    return f"id:{min(identifiers)}" if identifiers else normalize_name(canonical, group_kind)


def _link_supersessions(
    result: ExtractionResult,
    entities: list[GraphEntity],
    lookup: dict[str, set[UUID]],
    warnings: list[str],
) -> list[Supersession]:
    """Connect each replacing Decision to the one it replaces: `old.superseded_by = new.id`."""
    decision = EntityKind.DECISION.value
    pending: list[Supersession] = []
    by_id = {entity.id: index for index, entity in enumerate(entities)}
    for event in result.events:
        if event.kind is not EntityKind.DECISION or not event.supersedes:
            continue
        news = lookup.get(f"{decision}:{normalize_name(event.name, decision)}", set())
        if len(news) != 1:
            warnings.append(f"대체하는 결정을 특정할 수 없어 연결하지 않았습니다: {event.name}")
            continue
        (new_id,) = news
        old_key = normalize_name(event.supersedes, decision)
        olds = lookup.get(f"{decision}:{old_key}", set())
        if new_id in olds:
            warnings.append(f"결정이 자기 자신을 대체할 수 없습니다: {event.name}")
        elif len(olds) > 1:
            warnings.append(f"대체되는 결정이 모호해 연결하지 않았습니다: {event.supersedes}")
        elif olds:
            (old_id,) = olds
            index = by_id[old_id]
            if entities[index].superseded_by not in (None, new_id):
                warnings.append(f"이미 다른 결정으로 대체된 결정입니다: {event.supersedes}")
            else:
                entities[index] = entities[index].model_copy(update={"superseded_by": new_id})
        else:
            pending.append(
                Supersession(new_id=new_id, old_name=event.supersedes, old_keys=[old_key])
            )
    return pending


def resolve_extraction(
    result: ExtractionResult,
    *,
    workspace_id: UUID,
    source_id: UUID,
    chunk_id: UUID | None = None,
    timestamp: datetime | None = None,
    trusted_directory_identifiers: set[str] | None = None,
) -> ResolvedGraph:
    """Merge mentions of the same entity; never merge on name alone when identifiers disagree.

    - A shared identifier (email etc.) always means the same entity, whatever the names.
    - Same kind and shared normalized name/alias merge, unless both sides carry identifiers
      that do not overlap (homonyms).
    - A mention without identifiers that fits several distinct same-name entities is ambiguous,
      so it stays separate and is reported instead of being guessed.
    Events (Meeting/Decision/Task/...) are graph entities too and are resolved together.
    """
    warnings: list[str] = []
    trusted = trusted_directory_identifiers or set()
    mentions: list[tuple[str, str, list[str], set[str], datetime | None]] = [
        (
            item.name,
            item.kind.value,
            item.aliases,
            {
                normalized
                for value in item.identifiers
                if (normalized := normalize_identifier(value))
                and (not normalized.startswith("directory:") or normalized in trusted)
            },
            None,
        )
        for item in result.entities
    ] + [
        (item.name, item.kind.value, [], set(), parse_instant(item.occurred_at))
        for item in result.events
    ]

    groups: list[_Group] = []
    for name, kind, aliases, identifiers, occurred_at in mentions:
        keys = {normalize_name(value, kind) for value in [name, *aliases]} - {""}
        if not keys:
            warnings.append(f"이름이 비어 있는 개체를 버렸습니다: {name!r}")
            continue
        same_kind = [group for group in groups if group.kind == kind]
        by_identifier = [group for group in same_kind if group.identifiers & identifiers]
        by_name = [
            group
            for group in same_kind
            if group.keys & keys
            and group not in by_identifier
            and (not identifiers or not group.identifiers)  # both identified => homonym
        ]
        if by_identifier:
            matched = by_identifier + [group for group in by_name if not group.identifiers]
        elif not identifiers and sum(1 for group in by_name if group.identifiers) > 1:
            warnings.append(
                f"이름이 같은 개체가 여러 명이라 하나로 합치지 않았습니다: {name} "
                "(이메일 등 식별 정보가 필요합니다)"
            )
            matched = []
        else:
            matched = by_name
        if matched:
            group, *others = matched
            for other in others:
                group.absorb(other)
                groups.remove(other)
        else:
            group = _Group(kind)
            groups.append(group)
        group.names += [name, *aliases]
        group.keys |= keys
        group.identifiers |= identifiers
        group.timestamp = group.timestamp or occurred_at

    entities: list[GraphEntity] = []
    lookup: dict[str, set[UUID]] = {}
    for group in groups:
        canonical = pick_canonical(group.names, group.kind)
        identifier = entity_id(
            workspace_id, group.kind, _stable_key(group.kind, canonical, group.identifiers)
        )
        entities.append(
            GraphEntity(
                id=identifier,
                workspace_id=workspace_id,
                kind=group.kind,
                name=canonical,
                aliases=[name for name in dict.fromkeys(group.names) if name != canonical],
                keys=sorted(group.keys),
                identifiers=sorted(group.identifiers),
                evidence=GraphEvidence(
                    source_id=source_id,
                    chunk_id=chunk_id,
                    timestamp=group.timestamp or timestamp,
                ),
            )
        )
        for group_key in group.keys:
            lookup.setdefault(f"{group.kind}:{group_key}", set()).add(identifier)

    supersessions = _link_supersessions(result, entities, lookup, warnings)

    def endpoint(name: str) -> UUID | None:
        # Relation stage refers to entities by name only, so match across kinds.
        candidates: set[UUID] = set()
        for kind in EntityKind:
            candidates |= lookup.get(f"{kind.value}:{normalize_name(name, kind.value)}", set())
        if len(candidates) > 1:
            warnings.append(f"이름이 같은 개체가 여러 개라 관계 끝점을 정할 수 없습니다: {name}")
            return None
        return next(iter(candidates), None)

    fallback_start = as_utc(timestamp)
    intervals: dict[tuple[UUID, UUID, str], list[Interval]] = {}
    for relation in result.relations:
        source, target = endpoint(relation.source), endpoint(relation.target)
        if source is None or target is None:
            warnings.append(
                f"병합 후 개체를 찾지 못한 관계를 버렸습니다: {relation.source} → {relation.target}"
            )
            continue
        stated_from = parse_instant(relation.valid_from)
        valid_to = parse_instant(relation.valid_to)
        start = stated_from or fallback_start
        if valid_to and start and start > valid_to:
            if stated_from:
                warnings.append(
                    f"종료가 시작보다 빨라 valid_to를 버렸습니다: "
                    f"{relation.source} → {relation.target}"
                )
                valid_to = None
            else:
                start = None  # the source date is later than the stated end: start is unknown
        intervals.setdefault((source, target, relation.kind.value), []).append(
            Interval(start, valid_to)
        )

    evidence = GraphEvidence(source_id=source_id, chunk_id=chunk_id, timestamp=timestamp)
    relations: list[GraphRelation] = []
    for (source, target, kind), spans in intervals.items():
        for span in normalize(spans):  # a relation's validity periods never overlap
            relations.append(
                GraphRelation(
                    id=relation_id(workspace_id, source, target, kind, span.valid_from),
                    workspace_id=workspace_id,
                    source_entity_id=source,
                    target_entity_id=target,
                    kind=kind,
                    evidence=evidence,
                    valid_from=span.valid_from,
                    valid_to=span.valid_to,
                )
            )
    return ResolvedGraph(
        entities=entities, relations=relations, warnings=warnings, supersessions=supersessions
    )

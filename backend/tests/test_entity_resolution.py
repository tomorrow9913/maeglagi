from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.context_engine.application.entity_resolution import (
    normalize_name,
    resolve_extraction,
)
from app.modules.context_engine.domain.extraction import (
    ClassificationOutput,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedRelation,
    ExtractionResult,
)
from app.modules.context_engine.domain.ontology import EntityKind, RelationKind
from app.modules.retrieval.infrastructure.graph_writer import GraphWriter

WORKSPACE = uuid4()
SOURCE = uuid4()


def entity(name: str, kind: EntityKind, aliases: list[str] | None = None) -> ExtractedEntity:
    return ExtractedEntity(name=name, kind=kind, aliases=aliases or [], source_refs=["근거"])


def relation(source: str, target: str, kind: RelationKind) -> ExtractedRelation:
    return ExtractedRelation(source=source, target=target, kind=kind, source_refs=["근거"])


def extraction(
    entities: list[ExtractedEntity],
    relations: list[ExtractedRelation] | None = None,
    events: list[ExtractedEvent] | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        classification=ClassificationOutput(source_type="meeting", language="ko", topics=[]),
        entities=entities,
        events=events or [],
        relations=relations or [],
        contexts=[],
        warnings=[],
        usage={},
    )


def resolve(result: ExtractionResult, workspace_id: UUID = WORKSPACE):  # type: ignore[no-untyped-def]
    return resolve_extraction(result, workspace_id=workspace_id, source_id=SOURCE)


def test_normalization_ignores_case_spacing_and_person_honorifics() -> None:
    assert normalize_name(" Redis ", "Technology") == normalize_name("REDIS", "Technology")
    assert normalize_name("김민수 님", "Person") == normalize_name("김민수", "Person")
    assert normalize_name("김 민수", "Person") == "김민수"
    # Honorific stripping is only for people; it must not mangle other kinds.
    assert normalize_name("결정님", "Decision") == "결정님"


def test_same_person_written_differently_becomes_one_node() -> None:
    graph = resolve(
        extraction(
            [
                entity("김민수", EntityKind.PERSON, aliases=["민수"]),
                entity("민수 님", EntityKind.PERSON),
                entity("김민수 님", EntityKind.PERSON),
            ]
        )
    )

    assert len(graph.entities) == 1
    person = graph.entities[0]
    assert person.name == "김민수"
    assert "민수" in person.aliases


def test_same_name_of_different_kinds_stays_separate() -> None:
    graph = resolve(
        extraction([entity("Redis", EntityKind.TECHNOLOGY), entity("redis", EntityKind.PROJECT)])
    )

    assert sorted(item.kind for item in graph.entities) == ["Project", "Technology"]


def test_mention_bridging_two_groups_folds_them_together() -> None:
    graph = resolve(
        extraction(
            [
                entity("김민수", EntityKind.PERSON),
                entity("M. Kim", EntityKind.PERSON),
                entity("김민수", EntityKind.PERSON, aliases=["M. Kim"]),
            ]
        )
    )

    assert len(graph.entities) == 1


def test_ids_are_deterministic_and_scoped_to_the_workspace() -> None:
    result = extraction([entity("김민수", EntityKind.PERSON)])

    first = resolve(result).entities[0].id
    again = resolve(result).entities[0].id
    other = resolve(result, workspace_id=uuid4()).entities[0].id

    assert first == again
    assert first != other


def test_relations_follow_merged_nodes_and_collapse_duplicates() -> None:
    graph = resolve(
        extraction(
            [
                entity("김민수", EntityKind.PERSON, aliases=["민수"]),
                entity("민수", EntityKind.PERSON),
                entity("맥락이", EntityKind.PROJECT),
            ],
            [
                relation("김민수", "맥락이", RelationKind.WORKS_ON),
                relation("민수", "맥락이", RelationKind.WORKS_ON),
            ],
        )
    )

    assert len(graph.entities) == 2
    assert len(graph.relations) == 1
    ids = {item.id for item in graph.entities}
    assert graph.relations[0].source_entity_id in ids
    assert graph.relations[0].target_entity_id in ids


def test_events_are_resolved_as_entities_and_can_be_relation_endpoints() -> None:
    graph = resolve(
        extraction(
            [entity("김민수", EntityKind.PERSON)],
            [relation("김민수", "출시 회의", RelationKind.PARTICIPATED_IN)],
            events=[
                ExtractedEvent(
                    name="출시 회의",
                    kind=EntityKind.MEETING,
                    description="",
                    occurred_at="2026-09-14",
                    due_at=None,
                    source_refs=["근거"],
                )
            ],
        )
    )

    meeting = next(item for item in graph.entities if item.kind == "Meeting")
    assert meeting.evidence.timestamp is not None
    assert graph.relations[0].target_entity_id == meeting.id


def test_relation_to_unknown_entity_is_dropped_with_warning() -> None:
    graph = resolve(
        extraction(
            [entity("김민수", EntityKind.PERSON)],
            [relation("김민수", "없는 개체", RelationKind.CREATED)],
        )
    )

    assert graph.relations == []
    assert len(graph.warnings) == 1


class FakeStore:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        self.calls.append((query, parameters or {}))
        return self.existing if "RETURN row.id AS row_id" in query else []


def writer(store: FakeStore) -> GraphWriter:
    return GraphWriter(store)  # type: ignore[arg-type]


async def test_writer_upserts_entities_then_relations_by_kind() -> None:
    graph = resolve(
        extraction(
            [entity("김민수", EntityKind.PERSON), entity("맥락이", EntityKind.PROJECT)],
            [relation("김민수", "맥락이", RelationKind.WORKS_ON)],
        )
    )
    store = FakeStore()

    await writer(store).write(graph)

    queries = [query for query, _ in store.calls]
    assert "MERGE (e:Entity {id: row.id})" in queries[1]
    assert "MERGE (a)-[r:WORKS_ON]->(b)" in queries[2]
    rows = store.calls[1][1]["rows"]
    assert {row["name"] for row in rows} == {"김민수", "맥락이"}
    assert all(row["source_ids"] == [str(SOURCE)] for row in rows)


async def test_writer_is_a_noop_for_an_empty_graph() -> None:
    store = FakeStore()

    await writer(store).write(resolve(extraction([])))

    assert store.calls == []


async def test_writer_reuses_a_node_created_by_another_source() -> None:
    graph = resolve(
        extraction(
            [
                entity("민수", EntityKind.PERSON),
                entity("맥락이", EntityKind.PROJECT),
            ],
            [relation("민수", "맥락이", RelationKind.WORKS_ON)],
        )
    )
    new = next(item for item in graph.entities if item.kind == "Person")
    existing_id = uuid4()
    other_source = str(uuid4())
    store = FakeStore(
        [
            {
                "row_id": str(new.id),
                "id": str(existing_id),
                "name": "김민수",
                "aliases": ["민수"],
                "keys": ["김민수", "민수"],
                "source_ids": [other_source],
            }
        ]
    )

    await writer(store).write(graph)

    person = next(row for row in store.calls[1][1]["rows"] if row["kind"] == "Person")
    assert person["id"] == str(existing_id)
    assert person["name"] == "김민수"
    assert set(person["source_ids"]) == {other_source, str(SOURCE)}
    project_id = next(item.id for item in graph.entities if item.kind == "Project")
    edge = store.calls[2][1]["rows"][0]
    assert edge["source_entity_id"] == str(existing_id)
    assert edge["target_entity_id"] == str(project_id)


async def test_writer_rejects_relation_kinds_outside_the_ontology() -> None:
    graph = resolve(
        extraction(
            [entity("김민수", EntityKind.PERSON), entity("맥락이", EntityKind.PROJECT)],
            [relation("김민수", "맥락이", RelationKind.WORKS_ON)],
        )
    )
    graph.relations[0].kind = "OWNS} DETACH DELETE (n) //"

    with pytest.raises(ValueError):
        await writer(FakeStore()).write(graph)

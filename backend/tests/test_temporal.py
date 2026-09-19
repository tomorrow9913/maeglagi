from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.context_engine.application.entity_resolution import (
    ResolvedGraph,
    resolve_extraction,
)
from app.modules.context_engine.application.temporal import Interval, normalize, parse_instant
from app.modules.context_engine.domain.extraction import ExtractedEvent
from app.modules.context_engine.domain.ontology import EntityKind, RelationKind
from app.modules.retrieval.infrastructure.graph_writer import GraphWriter
from app.modules.retrieval.infrastructure.temporal_queries import TemporalQueries
from tests.test_entity_resolution import (
    WORKSPACE,
    FakeStore,
    entity,
    extraction,
    relation,
)


def day(value: str) -> datetime:
    parsed = parse_instant(value)
    assert parsed is not None
    return parsed


def span(start: str | None, end: str | None) -> Interval:
    return Interval(day(start) if start else None, day(end) if end else None)


def decision(name: str, at: str | None = None, supersedes: str | None = None) -> ExtractedEvent:
    return ExtractedEvent(
        name=name,
        kind=EntityKind.DECISION,
        description="",
        occurred_at=at,
        due_at=None,
        supersedes=supersedes,
        source_refs=["근거"],
    )


def resolve(result, source_date: datetime | None = None) -> ResolvedGraph:  # type: ignore[no-untyped-def]
    return resolve_extraction(
        result, workspace_id=WORKSPACE, source_id=uuid4(), timestamp=source_date
    )


def works_on(**dates: str | None):  # type: ignore[no-untyped-def]
    return extraction(
        [entity("김민수", EntityKind.PERSON), entity("맥락이", EntityKind.PROJECT)],
        [relation("김민수", "맥락이", RelationKind.WORKS_ON, **dates)],
    )


# --- intervals -----------------------------------------------------------------------------


def test_parse_instant_accepts_dates_and_zones_and_rejects_garbage() -> None:
    assert parse_instant("2026-09-12") == datetime(2026, 9, 12, tzinfo=UTC)
    assert parse_instant("2026-09-12T09:00:00+09:00") == datetime(2026, 9, 12, tzinfo=UTC)
    assert parse_instant("다음 주") is None
    assert parse_instant(None) is None


def test_disjoint_periods_stay_separate() -> None:
    result = normalize([span("2026-01-01", "2026-03-31"), span("2026-06-01", None)])

    assert result == [span("2026-01-01", "2026-03-31"), span("2026-06-01", None)]


def test_overlapping_periods_fold_into_one() -> None:
    result = normalize([span("2026-01-01", "2026-05-01"), span("2026-04-01", "2026-08-01")])

    assert result == [span("2026-01-01", "2026-08-01")]


def test_an_explicit_end_closes_an_open_period_and_keeps_the_known_start() -> None:
    assert normalize([span("2026-01-01", None), span(None, "2026-05-31")]) == [
        span("2026-01-01", "2026-05-31")
    ]


def test_a_later_open_period_does_not_reopen_a_closed_one() -> None:
    result = normalize([span("2026-01-01", "2026-05-31"), span("2026-05-01", None)])

    assert result == [span("2026-01-01", "2026-05-31")]


def test_periods_are_disjoint_after_normalizing() -> None:
    spans = normalize(
        [
            span("2026-01-01", "2026-02-01"),
            span("2026-01-15", "2026-03-01"),
            span("2026-06-01", None),
        ]
    )

    for first, second in zip(spans, spans[1:], strict=False):
        assert not first.overlaps(second)


# --- resolving relations -------------------------------------------------------------------


def test_relation_start_defaults_to_the_source_date_and_end_stays_unknown() -> None:
    graph = resolve(works_on(), source_date=day("2026-09-01"))

    assert (graph.relations[0].valid_from, graph.relations[0].valid_to) == (
        day("2026-09-01"),
        None,
    )


def test_stated_validity_is_recorded_as_written() -> None:
    graph = resolve(
        works_on(valid_from="2026-01-05", valid_to="2026-05-31"), source_date=day("2026-09-01")
    )

    assert (graph.relations[0].valid_from, graph.relations[0].valid_to) == (
        day("2026-01-05"),
        day("2026-05-31"),
    )


def test_end_before_a_stated_start_is_dropped_with_a_warning() -> None:
    graph = resolve(works_on(valid_from="2026-06-01", valid_to="2026-05-01"))

    assert graph.relations[0].valid_to is None
    assert any("valid_to를 버렸습니다" in warning for warning in graph.warnings)


def test_source_date_after_the_stated_end_leaves_the_start_unknown() -> None:
    graph = resolve(works_on(valid_to="2026-05-31"), source_date=day("2026-09-01"))

    assert (graph.relations[0].valid_from, graph.relations[0].valid_to) == (
        None,
        day("2026-05-31"),
    )


def test_repeated_relation_in_one_source_collapses_to_disjoint_periods() -> None:
    result = extraction(
        [entity("김민수", EntityKind.PERSON), entity("맥락이", EntityKind.PROJECT)],
        [
            relation("김민수", "맥락이", RelationKind.WORKS_ON, "2026-01-01", "2026-03-31"),
            relation("김민수", "맥락이", RelationKind.WORKS_ON, "2026-02-01", "2026-04-30"),
            relation("김민수", "맥락이", RelationKind.WORKS_ON, "2026-07-01", None),
        ],
    )

    graph = resolve(result)

    assert [(r.valid_from, r.valid_to) for r in graph.relations] == [
        (day("2026-01-01"), day("2026-04-30")),
        (day("2026-07-01"), None),
    ]
    assert len({r.id for r in graph.relations}) == 2


# --- superseding decisions -----------------------------------------------------------------


def test_a_decision_replaced_within_one_source_points_at_its_successor() -> None:
    graph = resolve(
        extraction(
            [],
            events=[
                decision("캐시를 두지 않는다", "2026-09-01"),
                decision("Redis 도입", "2026-09-12", supersedes="캐시를 두지 않는다"),
            ],
        )
    )

    old = next(e for e in graph.entities if e.name == "캐시를 두지 않는다")
    new = next(e for e in graph.entities if e.name == "Redis 도입")
    assert old.superseded_by == new.id
    assert new.superseded_by is None
    assert graph.supersessions == []


def test_a_decision_replacing_one_from_another_source_is_left_for_the_writer() -> None:
    graph = resolve(
        extraction([], events=[decision("Redis 도입", "2026-09-12", supersedes="캐시 없음")])
    )

    (pending,) = graph.supersessions
    assert pending.new_id == graph.entities[0].id
    assert pending.old_name == "캐시 없음"
    assert graph.entities[0].superseded_by is None


def test_no_supersession_is_invented_when_the_source_does_not_state_one() -> None:
    graph = resolve(
        extraction([], events=[decision("A", "2026-09-01"), decision("B", "2026-09-12")])
    )

    assert all(e.superseded_by is None for e in graph.entities)
    assert graph.supersessions == []


def test_a_decision_cannot_supersede_itself() -> None:
    graph = resolve(extraction([], events=[decision("Redis 도입", supersedes="Redis 도입")]))

    assert graph.entities[0].superseded_by is None
    assert any("자기 자신" in warning for warning in graph.warnings)


# --- writing -------------------------------------------------------------------------------


def writer(store: FakeStore) -> GraphWriter:
    return GraphWriter(store)  # type: ignore[arg-type]


def stored(source: Any, target: Any, start: str | None, end: str | None) -> dict[str, Any]:
    return {"source": str(source), "target": str(target), "valid_from": start, "valid_to": end}


async def write_relation(graph: ResolvedGraph, stored_rows: list[dict[str, Any]]) -> FakeStore:
    store = FakeStore(relations=stored_rows)
    await writer(store).write(graph)
    return store


async def test_a_later_source_closes_a_stored_open_relation() -> None:
    graph = resolve(works_on(valid_to="2026-05-31"), source_date=day("2026-09-01"))
    edge = graph.relations[0]
    open_edge = stored(edge.source_entity_id, edge.target_entity_id, "2026-01-01T00:00:00Z", None)

    store = await write_relation(graph, [open_edge])

    (row,) = store.rows("MERGE (a)-[r:WORKS_ON")
    assert row["valid_from"] == "2026-01-01T00:00:00+00:00"
    assert row["valid_to"] == "2026-05-31T00:00:00+00:00"


async def test_rejoining_after_an_end_keeps_two_disjoint_periods() -> None:
    graph = resolve(works_on(valid_from="2026-07-01"), source_date=day("2026-09-01"))
    edge = graph.relations[0]
    closed = stored(
        edge.source_entity_id,
        edge.target_entity_id,
        "2026-01-01T00:00:00Z",
        "2026-05-31T00:00:00Z",
    )

    store = await write_relation(graph, [closed])

    rows = store.rows("MERGE (a)-[r:WORKS_ON")
    assert [(r["valid_from"][:10], (r["valid_to"] or "")[:10]) for r in rows] == [
        ("2026-01-01", "2026-05-31"),
        ("2026-07-01", ""),
    ]
    (cleanup,) = store.rows("WHERE r.id IS NULL OR NOT r.id IN row.keep_ids")
    assert sorted(cleanup["keep_ids"]) == sorted(r["id"] for r in rows)


async def test_rewriting_the_same_source_is_idempotent() -> None:
    graph = resolve(works_on(valid_from="2026-01-05"), source_date=day("2026-09-01"))

    first = await write_relation(graph, [])
    edge = graph.relations[0]
    again = await write_relation(
        graph,
        [stored(edge.source_entity_id, edge.target_entity_id, "2026-01-05T00:00:00Z", None)],
    )

    assert first.rows("MERGE (a)-[r:WORKS_ON") == again.rows("MERGE (a)-[r:WORKS_ON")


async def test_entity_upsert_never_erases_an_existing_superseded_by() -> None:
    store = FakeStore()
    await writer(store).write(resolve(extraction([entity("맥락이", EntityKind.PROJECT)])))

    upsert = next(query for query, _ in store.calls if "MERGE (e:Entity" in query)
    assert "coalesce(row.superseded_by, e.superseded_by)" in upsert


async def test_writer_links_a_new_decision_to_the_stored_one_it_replaces() -> None:
    graph = resolve(
        extraction([], events=[decision("Redis 도입", "2026-09-12", supersedes="캐시 없음")])
    )
    new_id = graph.entities[0].id
    store = FakeStore(superseded=[{"new_id": str(new_id), "id": str(uuid4())}])

    warnings = await writer(store).write(graph)

    (row,) = store.rows("SET old.superseded_by")
    assert row["new_id"] == str(new_id)
    assert row["keys"] == ["캐시없음"]
    assert warnings == []


async def test_writer_warns_when_the_replaced_decision_is_not_found() -> None:
    graph = resolve(
        extraction([], events=[decision("Redis 도입", "2026-09-12", supersedes="없는 결정")])
    )

    warnings = await writer(FakeStore()).write(graph)

    assert len(warnings) == 1
    assert "없는 결정" in warnings[0]


# --- reading (what the demo shows) ---------------------------------------------------------


async def test_demo_the_redis_decision_replaces_no_cache_and_history_shows_it() -> None:
    old_id, new_id = uuid4(), uuid4()
    store = FakeStore()

    async def execute(query: str, parameters: dict[str, Any] | None = None) -> Any:
        store.calls.append((query, parameters or {}))
        return [
            {
                "id": str(old_id),
                "name": "캐시를 두지 않는다",
                "decided_at": "2026-09-01T00:00:00Z",
                "superseded_by": str(new_id),
                "superseded_by_name": "Redis 도입",
            },
            {
                "id": str(new_id),
                "name": "Redis 도입",
                "decided_at": "2026-09-12T00:00:00Z",
                "superseded_by": None,
                "superseded_by_name": None,
            },
        ]

    store.execute = execute  # type: ignore[method-assign]
    queries = TemporalQueries(store)  # type: ignore[arg-type]

    history = await queries.decision_history(WORKSPACE)
    current = await queries.current_decisions(WORKSPACE)

    assert [(d.name, d.is_current) for d in history] == [
        ("캐시를 두지 않는다", False),
        ("Redis 도입", True),
    ]
    assert history[0].superseded_by_name == "Redis 도입"
    assert [d.name for d in current] == ["Redis 도입"]


async def test_relations_as_of_filters_on_the_given_instant() -> None:
    store = FakeStore()

    async def execute(query: str, parameters: dict[str, Any] | None = None) -> Any:
        store.calls.append((query, parameters or {}))
        return [
            {
                "source": "김민수",
                "kind": "WORKS_ON",
                "target": "맥락이",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": None,
            }
        ]

    store.execute = execute  # type: ignore[method-assign]

    found = await TemporalQueries(store).relations_as_of(  # type: ignore[arg-type]
        WORKSPACE, datetime(2026, 3, 1)
    )

    query, params = store.calls[0]
    assert "r.valid_to IS NULL OR r.valid_to >= datetime($at)" in query
    assert params["at"] == "2026-03-01T00:00:00+00:00"
    assert "WORKS_ON" in params["kinds"]
    assert (found[0].source, found[0].valid_to) == ("김민수", None)

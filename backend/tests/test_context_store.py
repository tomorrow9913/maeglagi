from typing import Any
from uuid import uuid4

from app.modules.context_engine.application.context_store import (
    ContextStoreService,
    ContextStoreUpdater,
    merge_extraction,
    state_from_record,
    timeline_records,
)
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.domain.context_store import (
    ContextStoreState,
    StoreAction,
    StoreItem,
)
from app.modules.context_engine.domain.extraction import (
    ClassificationOutput,
    ExtractedEntity,
    ExtractedEvent,
    ExtractedRelation,
    ExtractionResult,
)
from app.modules.context_engine.domain.ontology import EntityKind, RelationKind
from tests.test_extraction_pipeline import FakeAdapter
from tests.test_source_analysis import FakeRepository

WORKSPACE, OWNER = uuid4(), uuid4()
TEXT = "지훈: 응답 지연 문제는 캐시 도입으로 해결됐습니다. 서연은 무효화 규칙 초안을 끝냈습니다."


def event(
    name: str,
    kind: EntityKind,
    description: str = "",
    at: str | None = None,
    due: str | None = None,
    supersedes: str | None = None,
) -> ExtractedEvent:
    return ExtractedEvent(
        name=name,
        kind=kind,
        description=description,
        occurred_at=at,
        due_at=due,
        supersedes=supersedes,
        source_refs=["근거"],
    )


def result(events: list[ExtractedEvent], **extra: Any) -> ExtractionResult:
    return ExtractionResult(
        classification=ClassificationOutput(source_type="meeting", language="ko", topics=[]),
        entities=extra.get("entities", []),
        events=events,
        relations=extra.get("relations", []),
        contexts=extra.get("contexts", []),
        warnings=[],
        usage={},
    )


def empty() -> ContextStoreState:
    return ContextStoreState(subject="맥락이 PoC")


# --- deterministic merge ------------------------------------------------------------------------


def test_decisions_issues_and_tasks_land_in_the_matching_lists() -> None:
    merged = merge_extraction(
        empty(),
        result(
            [
                event("Redis 도입", EntityKind.DECISION, "재생성 가능한 캐시로만", "2026-09-12"),
                event("응답 지연", EntityKind.ISSUE, "p95 1.8초"),
                event("무효화 규칙 초안", EntityKind.TASK, "", due="2026-09-19"),
                event("아키텍처 회의", EntityKind.MEETING),
            ]
        ),
        uuid4(),
    )

    assert [d.title for d in merged.decisions] == ["Redis 도입"]
    assert merged.decisions[0].decided_at == "2026-09-12"
    assert [i.title for i in merged.open_issues] == ["응답 지연"]
    assert [(a.title, a.due_at) for a in merged.next_actions] == [
        ("무효화 규칙 초안", "2026-09-19")
    ]


def test_a_task_carries_its_assignee_from_the_relations() -> None:
    merged = merge_extraction(
        empty(),
        result(
            [event("무효화 규칙 초안", EntityKind.TASK)],
            entities=[
                ExtractedEntity(
                    name="최서연",
                    kind=EntityKind.PERSON,
                    aliases=[],
                    identifiers=[],
                    source_refs=["근거"],
                )
            ],
            relations=[
                ExtractedRelation(
                    source="무효화 규칙 초안",
                    target="최서연",
                    kind=RelationKind.ASSIGNED_TO,
                    valid_from=None,
                    valid_to=None,
                    source_refs=["근거"],
                )
            ],
        ),
        uuid4(),
    )

    assert merged.next_actions[0].assignee == "최서연"


def test_reprocessing_a_source_replaces_its_items_instead_of_duplicating_them() -> None:
    source = uuid4()
    first = merge_extraction(
        empty(), result([event("응답 지연", EntityKind.ISSUE, "처음")]), source
    )

    again = merge_extraction(first, result([event("응답  지연", EntityKind.ISSUE, "고침")]), source)

    assert [(i.title, i.description) for i in again.open_issues] == [("응답  지연", "고침")]
    assert again.source_ids == [str(source)]


def test_a_replaced_decision_leaves_the_current_state() -> None:
    state = merge_extraction(
        empty(), result([event("캐시를 두지 않는다", EntityKind.DECISION)]), uuid4()
    )

    merged = merge_extraction(
        state,
        result([event("Redis 도입", EntityKind.DECISION, supersedes="캐시를 두지 않는다")]),
        uuid4(),
    )

    assert [d.title for d in merged.decisions] == ["Redis 도입"]


def test_a_decision_never_removes_itself_and_unknown_targets_change_nothing() -> None:
    state = merge_extraction(empty(), result([event("Redis 도입", EntityKind.DECISION)]), uuid4())

    merged = merge_extraction(
        state,
        result(
            [
                event("Redis 도입", EntityKind.DECISION, supersedes="Redis 도입"),
                event("다른 결정", EntityKind.DECISION, supersedes="없는 결정"),
            ]
        ),
        uuid4(),
    )

    assert {d.title for d in merged.decisions} == {"Redis 도입", "다른 결정"}


def test_sources_accumulate_and_merging_does_not_mutate_the_input() -> None:
    state = empty()

    merged = merge_extraction(state, result([event("A", EntityKind.ISSUE)]), uuid4())

    assert state.open_issues == [] and state.source_ids == []
    assert len(merged.source_ids) == 1


# --- timeline rows ------------------------------------------------------------------------------


def rows(events: list[ExtractedEvent]) -> list[Any]:
    return timeline_records(
        result(events), workspace_id=WORKSPACE, owner_id=OWNER, source_id=uuid4()
    )


def test_timeline_rows_use_the_kinds_the_frontend_draws() -> None:
    kinds = {
        r.title: r.kind
        for r in rows(
            [
                event("D", EntityKind.DECISION),
                event("I", EntityKind.ISSUE),
                event("T", EntityKind.TASK),
                event("M", EntityKind.MEETING),
                event("E", EntityKind.EVENT),
            ]
        )
    }

    assert kinds == {"D": "decision", "I": "issue", "T": "task", "M": "event", "E": "event"}


def test_a_timeline_row_always_has_a_body_and_a_parsed_time() -> None:
    (row,) = rows([event("출시 회의", EntityKind.MEETING, "", "2026-09-12")])

    assert row.body == "출시 회의"
    assert row.occurred_at is not None and row.occurred_at.year == 2026


def test_a_replacing_decision_row_remembers_which_decision_it_replaces() -> None:
    old, new = rows(
        [
            event("캐시를 두지 않는다", EntityKind.DECISION),
            event("Redis 도입", EntityKind.DECISION, supersedes="캐시를 두지 않는다"),
        ]
    )

    assert old.metadata_["supersedes"] is None
    assert new.metadata_["supersedes"] == old.metadata_["key"]


def test_duplicate_events_collapse_to_one_row() -> None:
    assert len(rows([event("A", EntityKind.ISSUE), event(" a ", EntityKind.ISSUE)])) == 1


# --- the model's part ---------------------------------------------------------------------------


def updater(update: dict[str, Any]) -> ContextStoreUpdater:
    base = {
        "summary": "요약",
        "current_state": "상황",
        "resolved_issues": [],
        "completed_actions": [],
    }
    adapter = FakeAdapter({"context_update": {**base, **update}})
    return ContextStoreUpdater(ExtractionPipeline(adapter, "key", model="m"))  # type: ignore[arg-type]


def with_open_work() -> ContextStoreState:
    return ContextStoreState(
        subject="맥락이 PoC",
        summary="이전 요약",
        current_state="이전 상황",
        open_issues=[
            StoreItem(title="응답 지연", description="", source_refs=["근거"]),
            StoreItem(title="정합성 우려", description="", source_refs=["근거"]),
        ],
    )


async def update(state: ContextStoreState, output: dict[str, Any], text: str = TEXT):
    return await updater(output).update(
        state, result([]), source_id=uuid4(), source_title="회의", text=text
    )


async def test_an_issue_is_closed_only_when_the_source_says_so_with_a_real_quote() -> None:
    closed, warnings = await update(
        with_open_work(),
        {
            "resolved_issues": [
                {
                    "title": "응답 지연",
                    "source_refs": ["응답 지연 문제는 캐시 도입으로 해결됐습니다."],
                }
            ]
        },
    )

    assert [i.title for i in closed.open_issues] == ["정합성 우려"]
    assert warnings == []


async def test_a_closure_quoting_text_that_is_not_in_the_source_is_ignored() -> None:
    state, warnings = await update(
        with_open_work(),
        {"resolved_issues": [{"title": "응답 지연", "source_refs": ["원문에 없는 문장입니다."]}]},
    )

    assert [i.title for i in state.open_issues] == ["응답 지연", "정합성 우려"]
    assert any("근거가 원문에 없어" in warning for warning in warnings)


async def test_a_closure_without_any_quote_is_ignored() -> None:
    state, _ = await update(
        with_open_work(), {"resolved_issues": [{"title": "응답 지연", "source_refs": []}]}
    )

    assert len(state.open_issues) == 2


async def test_closing_something_that_is_not_open_warns_and_changes_nothing() -> None:
    state, warnings = await update(
        with_open_work(),
        {
            "resolved_issues": [
                {
                    "title": "없는 이슈",
                    "source_refs": ["응답 지연 문제는 캐시 도입으로 해결됐습니다."],
                }
            ]
        },
    )

    assert len(state.open_issues) == 2
    assert any("찾지 못했습니다" in warning for warning in warnings)


async def test_the_model_cannot_drop_items_by_leaving_them_out() -> None:
    state, _ = await update(with_open_work(), {"summary": "새 요약"})

    assert [i.title for i in state.open_issues] == ["응답 지연", "정합성 우려"]


async def test_a_finished_action_is_removed_from_next_actions() -> None:
    state = ContextStoreState(
        subject="s",
        next_actions=[StoreAction(title="무효화 규칙 초안", description="", source_refs=["근거"])],
    )

    done, _ = await update(
        state,
        {
            "completed_actions": [
                {
                    "title": "무효화 규칙 초안",
                    "source_refs": ["서연은 무효화 규칙 초안을 끝냈습니다."],
                }
            ]
        },
    )

    assert done.next_actions == []


async def test_narrative_is_replaced_but_never_blanked() -> None:
    state, _ = await update(with_open_work(), {"summary": "  ", "current_state": "새 상황"})

    assert (state.summary, state.current_state) == ("이전 요약", "새 상황")
    assert state.updated_at is not None


# --- service ------------------------------------------------------------------------------------


def apply_kwargs(source: Any, extraction: ExtractionResult) -> dict[str, Any]:
    return {
        "workspace_id": WORKSPACE,
        "owner_id": OWNER,
        "source_id": source,
        "source_title": "회의",
        "subject": "맥락이 PoC",
        "text": TEXT,
        "result": extraction,
    }


async def test_the_store_accumulates_across_sources_in_one_record() -> None:
    repository = FakeRepository()
    service = ContextStoreService(repository, updater({}))
    first, second = uuid4(), uuid4()

    await service.apply(**apply_kwargs(first, result([event("응답 지연", EntityKind.ISSUE)])))
    record = repository.record
    await service.apply(**apply_kwargs(second, result([event("Redis 도입", EntityKind.DECISION)])))

    assert repository.record is record  # same row, updated in place
    state = state_from_record(record)  # type: ignore[arg-type]
    assert [i.title for i in state.open_issues] == ["응답 지연"]
    assert [d.title for d in state.decisions] == ["Redis 도입"]
    assert state.source_ids == [str(first), str(second)]
    assert set(repository.timeline) == {first, second}


async def test_current_decisions_are_what_a_new_decision_may_replace() -> None:
    repository = FakeRepository()
    service = ContextStoreService(repository, updater({}))
    assert await service.current_decisions(WORKSPACE) == []

    await service.apply(**apply_kwargs(uuid4(), result([event("Redis 도입", EntityKind.DECISION)])))

    assert await service.current_decisions(WORKSPACE) == ["Redis 도입"]

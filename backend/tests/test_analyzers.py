from typing import Any

import pytest

from app.modules.context_engine.application.analysis import DocumentAnalyzer, MeetingAnalyzer
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.domain.analysis import DocumentAnalysis, MeetingAnalysis
from tests.seeds import SEEDS, Seed
from tests.test_extraction_pipeline import FakeAdapter


def pipeline(adapter: FakeAdapter) -> ExtractionPipeline:
    return ExtractionPipeline(adapter, "key", model="test-model")  # type: ignore[arg-type]


def seed(name: str) -> Seed:
    return next(item for item in SEEDS if item.name == name)


async def analyze(item: Seed, responses: dict[str, Any] | None = None) -> Any:
    adapter = FakeAdapter(responses or item.responses)
    extraction = pipeline(adapter)
    if item.kind == "meeting":
        return await MeetingAnalyzer(extraction).analyze(item.text, title=item.title)
    return await DocumentAnalyzer(extraction).analyze(item.text, title=item.title)


@pytest.mark.parametrize("item", SEEDS, ids=[item.name for item in SEEDS])
async def test_every_seed_passes_the_contract(item: Seed) -> None:
    analysis = await analyze(item)

    model = MeetingAnalysis if item.kind == "meeting" else DocumentAnalysis
    assert model.model_validate(analysis.model_dump()) == analysis
    assert analysis.schema_version == "1"
    assert analysis.warnings == []  # every source_ref is a verbatim quote of the seed
    assert analysis.summary


async def test_meeting_analysis_has_decisions_action_items_and_issues() -> None:
    analysis = await analyze(seed("meeting-0912"))

    assert analysis.meeting_title == "아키텍처 회의"
    assert analysis.participants == ["박지훈", "최서연", "이도윤"]
    assert [item.title for item in analysis.decisions] == ["Redis 도입 결정"]
    assert analysis.decisions[0].decided_at == "2026-09-12"
    assert [(i.title, i.assignee) for i in analysis.action_items] == [
        ("캐시 무효화 규칙 초안 작성", "최서연")
    ]
    assert analysis.issues == []


async def test_performance_meeting_surfaces_the_latency_issue_and_its_task() -> None:
    analysis = await analyze(seed("meeting-0905"))

    assert [item.title for item in analysis.issues] == ["조회 API 응답 지연"]
    task = analysis.action_items[0]
    assert (task.assignee, task.due_at) == ("박지훈", "2026-09-08")
    assert analysis.decisions == []


async def test_planning_document_yields_project_goal_owner_schedule_and_systems() -> None:
    analysis = await analyze(seed("plan-0901"))

    brief = analysis.planning
    assert brief is not None
    assert brief.project == "API 성능 개선"
    assert "500ms" in (brief.goal or "")
    assert brief.owners == ["박지훈"]
    assert [(s.milestone, s.date) for s in brief.schedule] == [
        ("성능 회의", "2026-09-05"),
        ("아키텍처 회의", "2026-09-12"),
    ]
    assert brief.related_systems == ["PostgreSQL", "Redis"]
    assert analysis.projects == ["API 성능 개선"]


async def test_planning_step_runs_only_for_planning_documents() -> None:
    plan_adapter = FakeAdapter(seed("plan-0901").responses)
    await DocumentAnalyzer(pipeline(plan_adapter)).analyze("본문")
    report_adapter = FakeAdapter(seed("poc-0908").responses)
    report = await DocumentAnalyzer(pipeline(report_adapter)).analyze("본문")

    assert [r.schema_name for r in plan_adapter.requests][-1] == "extraction_planning"
    assert "extraction_planning" not in [r.schema_name for r in report_adapter.requests]
    assert report.planning is None


async def test_planning_brief_without_source_refs_is_dropped() -> None:
    item = seed("plan-0901")
    unsourced = {**item.responses, "planning": {**item.responses["planning"], "source_refs": []}}

    analysis = await analyze(item, unsourced)

    assert analysis.planning is None
    assert any("source_ref 없는 기획서 요약" in warning for warning in analysis.warnings)


async def test_quotes_missing_from_the_source_are_flagged_not_silently_trusted() -> None:
    item = seed("meeting-0912")
    altered = Seed(item.name, item.kind, item.title, "전혀 다른 원문입니다.", item.responses)

    analysis = await analyze(altered)

    assert any("원문에서 찾지 못한 근거" in warning for warning in analysis.warnings)
    assert analysis.decisions  # flagged, not dropped


async def test_meeting_analyzer_warns_when_given_a_non_meeting() -> None:
    item = seed("poc-0908")

    analysis = await MeetingAnalyzer(pipeline(FakeAdapter(item.responses))).analyze(item.text)

    assert any("회의 분석기" in warning for warning in analysis.warnings)


async def test_usage_is_reported() -> None:
    analysis = await analyze(seed("plan-0901"))

    assert analysis.usage["prompt_tokens"] == 60  # five stages + planning, 10 each

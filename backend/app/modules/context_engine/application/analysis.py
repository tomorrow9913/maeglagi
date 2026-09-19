import re
from typing import Any

from app.modules.context_engine.application import extraction_prompts as prompts
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.domain.analysis import (
    ActionItem,
    AnalysisItem,
    DecisionItem,
    DocumentAnalysis,
    MeetingAnalysis,
    NamedEntity,
    PlanningBrief,
)
from app.modules.context_engine.domain.extraction import ExtractedEvent, ExtractionResult
from app.modules.context_engine.domain.ontology import (
    ContextKind,
    EntityKind,
    RelationKind,
    SourceType,
)

_EVENT_KINDS = {"Meeting", "Event", "Decision", "Task", "Issue"}


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _unverified_refs(text: str, groups: list[tuple[str, list[str]]]) -> list[str]:
    """Contract: source_refs quote the original. Flag quotes that are not in the text."""
    haystack = _squash(text)
    return [
        f"원문에서 찾지 못한 근거: {label}"
        for label, refs in groups
        for ref in refs
        if _squash(ref) and _squash(ref) not in haystack
    ]


def _events(result: ExtractionResult, kind: EntityKind) -> list[ExtractedEvent]:
    return [event for event in result.events if event.kind is kind]


def _summary(result: ExtractionResult) -> str:
    for context in result.contexts:
        if context.kind is ContextKind.SUMMARY:
            return context.body
    return ""


def _assignee(result: ExtractionResult, task: str) -> str | None:
    people = {item.name for item in result.entities if item.kind is EntityKind.PERSON}
    for relation in result.relations:
        if relation.kind is not RelationKind.ASSIGNED_TO:
            continue
        if relation.source == task and relation.target in people:
            return relation.target
        if relation.target == task and relation.source in people:
            return relation.source
    return None


def _decisions(result: ExtractionResult) -> list[DecisionItem]:
    return [
        DecisionItem(
            title=item.name,
            description=item.description,
            decided_at=item.occurred_at,
            supersedes=item.supersedes,
            source_refs=item.source_refs,
        )
        for item in _events(result, EntityKind.DECISION)
    ]


def _tasks(result: ExtractionResult) -> list[ActionItem]:
    return [
        ActionItem(
            title=item.name,
            description=item.description,
            assignee=_assignee(result, item.name),
            due_at=item.due_at,
            source_refs=item.source_refs,
        )
        for item in _events(result, EntityKind.TASK)
    ]


def _issues(result: ExtractionResult) -> list[AnalysisItem]:
    return [
        AnalysisItem(title=item.name, description=item.description, source_refs=item.source_refs)
        for item in _events(result, EntityKind.ISSUE)
    ]


def _source_ref_groups(
    result: ExtractionResult, extra: list[tuple[str, list[str]]] | None = None
) -> list[tuple[str, list[str]]]:
    groups = [(item.name, item.source_refs) for item in [*result.entities, *result.events]]
    groups += [(item.title, item.source_refs) for item in result.contexts]
    return groups + (extra or [])


class MeetingAnalyzer:
    """Meeting transcript -> planner-confirmed JSON (decisions, action_items, issues)."""

    def __init__(self, pipeline: ExtractionPipeline) -> None:
        self.pipeline = pipeline

    async def analyze(
        self,
        transcript: str,
        *,
        title: str | None = None,
        known_decisions: list[str] | None = None,
    ) -> MeetingAnalysis:
        result = await self.pipeline.extract(
            transcript, title=title, known_decisions=known_decisions
        )
        warnings = list(result.warnings)
        if result.classification.source_type is not SourceType.MEETING:
            warnings.append(
                f"회의 분석기에 {result.classification.source_type.value} 자료가 들어왔습니다."
            )
        meeting = next(iter(_events(result, EntityKind.MEETING)), None)
        people = [item.name for item in result.entities if item.kind is EntityKind.PERSON]
        attendees = (
            [
                relation.source
                for relation in result.relations
                if relation.kind is RelationKind.PARTICIPATED_IN
                and meeting is not None
                and relation.target == meeting.name
                and relation.source in people
            ]
            if meeting
            else []
        )
        warnings += _unverified_refs(transcript, _source_ref_groups(result))
        return MeetingAnalysis(
            meeting_title=meeting.name if meeting else title,
            occurred_at=meeting.occurred_at if meeting else None,
            participants=list(dict.fromkeys(attendees or people)),
            summary=_summary(result),
            decisions=_decisions(result),
            action_items=_tasks(result),
            issues=_issues(result),
            warnings=warnings,
            usage=dict(result.usage),
        )


class DocumentAnalyzer:
    """Document -> planner-confirmed JSON; planning documents also get the TSK-50 brief."""

    def __init__(self, pipeline: ExtractionPipeline) -> None:
        self.pipeline = pipeline

    async def analyze(
        self,
        text: str,
        *,
        title: str | None = None,
        known_decisions: list[str] | None = None,
    ) -> DocumentAnalysis:
        result = await self.pipeline.extract(text, title=title, known_decisions=known_decisions)
        warnings = list(result.warnings)
        source_type = result.classification.source_type
        planning: PlanningBrief | None = None
        extra: list[tuple[str, list[str]]] = []
        if source_type is SourceType.PLAN:
            payload: dict[str, Any] = {"title": title, "text": text}
            brief = await self.pipeline.run_stage(
                "planning", prompts.PLANNING_PROMPT, payload, PlanningBrief
            )
            if any(ref.strip() for ref in brief.source_refs):
                planning = brief
                extra.append(("planning", brief.source_refs))
            else:
                warnings.append("planning: source_ref 없는 기획서 요약을 버렸습니다.")
        warnings += _unverified_refs(text, _source_ref_groups(result, extra))
        return DocumentAnalysis(
            title=title,
            source_type=source_type,
            summary=_summary(result),
            projects=[i.name for i in result.entities if i.kind is EntityKind.PROJECT],
            entities=[
                NamedEntity(name=i.name, kind=i.kind.value, source_refs=i.source_refs)
                for i in result.entities
                if i.kind.value not in _EVENT_KINDS and i.kind is not EntityKind.PROJECT
            ],
            issues=_issues(result),
            tasks=_tasks(result),
            decisions=_decisions(result),
            planning=planning,
            warnings=warnings,
            usage=dict(self.pipeline.usage),
        )

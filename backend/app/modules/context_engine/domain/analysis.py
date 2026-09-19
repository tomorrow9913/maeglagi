from pydantic import BaseModel, Field

from app.modules.context_engine.domain.extraction import StageOutput
from app.modules.context_engine.domain.ontology import SourceType

SCHEMA_VERSION = "1"


class AnalysisItem(BaseModel):
    """Common shape of everything a planner sees: a title, detail, and its evidence."""

    title: str
    description: str
    source_refs: list[str]


class DecisionItem(AnalysisItem):
    decided_at: str | None


class ActionItem(AnalysisItem):
    assignee: str | None
    due_at: str | None


class NamedEntity(BaseModel):
    name: str
    kind: str
    source_refs: list[str]


class ScheduleItem(StageOutput):
    milestone: str
    date: str | None


class PlanningBrief(StageOutput):
    """Fixed by TSK-50 for planning documents: Project, Goal, Owner, Schedule, Related Systems."""

    project: str | None
    goal: str | None
    owners: list[str]
    schedule: list[ScheduleItem]
    related_systems: list[str]
    source_refs: list[str]


class MeetingAnalysis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    meeting_title: str | None
    occurred_at: str | None
    participants: list[str]
    summary: str
    decisions: list[DecisionItem]
    action_items: list[ActionItem]
    issues: list[AnalysisItem]
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


class DocumentAnalysis(BaseModel):
    schema_version: str = SCHEMA_VERSION
    title: str | None
    source_type: SourceType
    summary: str
    projects: list[str]
    entities: list[NamedEntity]
    issues: list[AnalysisItem]
    tasks: list[ActionItem]
    decisions: list[DecisionItem]
    planning: PlanningBrief | None
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)

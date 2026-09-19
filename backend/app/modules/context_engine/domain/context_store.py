from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.context_engine.domain.extraction import StageOutput


class StoreItem(BaseModel):
    title: str
    description: str
    # Verbatim quotes from the source that support this item.
    source_refs: list[str]
    source_id: str | None = None


class StoreDecision(StoreItem):
    decided_at: str | None = None


class StoreAction(StoreItem):
    assignee: str | None = None
    due_at: str | None = None


class ContextStoreState(BaseModel):
    """PoC v1 Context Store: subject, summary, current_state, open_issues, decisions,
    next_actions, updated_at, source_refs (here `source_ids` plus each item's own refs)."""

    subject: str
    summary: str = ""
    current_state: str = ""
    open_issues: list[StoreItem] = Field(default_factory=list)
    decisions: list[StoreDecision] = Field(default_factory=list)
    next_actions: list[StoreAction] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class Resolution(StageOutput):
    """The model's claim that an existing open issue/action is finished, with proof."""

    title: str
    source_refs: list[str]


class ContextUpdateOutput(StageOutput):
    summary: str
    current_state: str
    resolved_issues: list[Resolution]
    completed_actions: list[Resolution]

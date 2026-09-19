from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.context_engine.application import extraction_prompts as prompts
from app.modules.context_engine.application.analysis import (
    assignee_of,
    squash,
    unverified_refs,
)
from app.modules.context_engine.application.entity_resolution import normalize_name
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.application.temporal import parse_instant
from app.modules.context_engine.domain.context_store import (
    ContextStoreState,
    ContextUpdateOutput,
    Resolution,
    StoreAction,
    StoreDecision,
    StoreItem,
)
from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import ContextKind, EntityKind
from app.modules.context_engine.infrastructure.models import ContextRecord, ContextStoreRecord

_TIMELINE_KIND = {
    EntityKind.DECISION: ContextKind.DECISION,
    EntityKind.ISSUE: ContextKind.ISSUE,
    EntityKind.TASK: ContextKind.TASK,
    EntityKind.MEETING: ContextKind.EVENT,
    EntityKind.EVENT: ContextKind.EVENT,
}


def item_key(title: str, kind: EntityKind) -> str:
    """Same normalization the graph uses, so an item keeps its identity across sources."""
    return normalize_name(title, kind.value)


def _upsert[T: StoreItem](items: list[T], new: T, kind: EntityKind) -> list[T]:
    key = item_key(new.title, kind)
    for index, item in enumerate(items):
        if item_key(item.title, kind) == key:
            items[index] = new
            return items
    return [*items, new]


def merge_extraction(
    state: ContextStoreState, result: ExtractionResult, source_id: UUID
) -> ContextStoreState:
    """Fold one source's decisions, issues and tasks into the store by key.

    Deterministic on purpose: nothing here can be lost or invented by a model. Reprocessing the
    same source replaces its items instead of duplicating them.
    """
    merged = state.model_copy(deep=True)
    sid = str(source_id)
    for event in result.events:
        if event.kind is EntityKind.DECISION:
            merged.decisions = _upsert(
                merged.decisions,
                StoreDecision(
                    title=event.name,
                    description=event.description,
                    decided_at=event.occurred_at,
                    source_refs=event.source_refs,
                    source_id=sid,
                ),
                event.kind,
            )
        elif event.kind is EntityKind.ISSUE:
            merged.open_issues = _upsert(
                merged.open_issues,
                StoreItem(
                    title=event.name,
                    description=event.description,
                    source_refs=event.source_refs,
                    source_id=sid,
                ),
                event.kind,
            )
        elif event.kind is EntityKind.TASK:
            merged.next_actions = _upsert(
                merged.next_actions,
                StoreAction(
                    title=event.name,
                    description=event.description,
                    assignee=assignee_of(result, event.name),
                    due_at=event.due_at,
                    source_refs=event.source_refs,
                    source_id=sid,
                ),
                event.kind,
            )
    # A replaced decision is history, not the current state.
    for event in result.events:
        if event.kind is EntityKind.DECISION and event.supersedes:
            replaced = item_key(event.supersedes, EntityKind.DECISION)
            if replaced != item_key(event.name, EntityKind.DECISION):
                merged.decisions = [
                    d
                    for d in merged.decisions
                    if item_key(d.title, EntityKind.DECISION) != replaced
                ]
    if sid not in merged.source_ids:
        merged.source_ids.append(sid)
    return merged


def timeline_records(
    result: ExtractionResult, *, workspace_id: UUID, owner_id: UUID, source_id: UUID
) -> list[ContextRecord]:
    """Timeline rows (`contexts`) for one source: one per decision/issue/task/event.

    A decision row remembers which earlier decision it replaces, so readers can mark the old one
    as superseded without touching the graph.
    """
    records: dict[tuple[str, str], ContextRecord] = {}
    for event in result.events:
        kind = _TIMELINE_KIND.get(event.kind)
        if kind is None:
            continue
        key = item_key(event.name, event.kind)
        if (kind.value, key) in records:
            continue
        replaces = (
            item_key(event.supersedes, EntityKind.DECISION)
            if event.kind is EntityKind.DECISION and event.supersedes
            else None
        )
        records[(kind.value, key)] = ContextRecord(
            workspace_id=workspace_id,
            source_id=source_id,
            owner_id=owner_id,
            kind=kind.value,
            title=event.name.strip()[:255],
            body=event.description.strip() or event.name.strip(),
            occurred_at=parse_instant(event.occurred_at),
            metadata_={
                "key": key,
                "supersedes": replaces if replaces != key else None,
                "due_at": event.due_at,
                "assignee": assignee_of(result, event.name)
                if event.kind is EntityKind.TASK
                else None,
                "source_refs": event.source_refs,
            },
        )
    return list(records.values())


def _grounded(resolution: Resolution, text: str) -> bool:
    """Closing something needs proof: every quoted ref must really be in the source."""
    refs = [ref for ref in resolution.source_refs if ref.strip()]
    haystack = squash(text)
    return bool(refs) and all(squash(ref) in haystack for ref in refs)


def _close(
    items: list[Any], resolutions: list[Resolution], kind: EntityKind, text: str, label: str
) -> tuple[list[Any], list[str]]:
    warnings: list[str] = []
    remaining = list(items)
    for resolution in resolutions:
        key = item_key(resolution.title, kind)
        target = next((i for i in remaining if item_key(i.title, kind) == key), None)
        if target is None:
            warnings.append(f"{label} 처리할 항목을 찾지 못했습니다: {resolution.title}")
        elif not _grounded(resolution, text):
            warnings.append(f"근거가 원문에 없어 {label} 처리를 무시했습니다: {resolution.title}")
        else:
            remaining.remove(target)
    return remaining, warnings


class ContextStoreUpdater:
    """Merge a new source into the store, then let the model write the narrative.

    The model only writes `summary`/`current_state` and may *close* an open issue or action when
    the source says so, with a quote. It cannot drop anything else.
    """

    def __init__(self, pipeline: ExtractionPipeline) -> None:
        self.pipeline = pipeline

    async def update(
        self,
        state: ContextStoreState,
        result: ExtractionResult,
        *,
        source_id: UUID,
        source_title: str,
        text: str,
    ) -> tuple[ContextStoreState, list[str]]:
        merged = merge_extraction(state, result, source_id)
        summary = next((c.body for c in result.contexts if c.kind is ContextKind.SUMMARY), "")
        payload: dict[str, Any] = {
            "subject": merged.subject,
            "previous": {"summary": state.summary, "current_state": state.current_state},
            "current": {
                "open_issues": [
                    i.model_dump(include={"title", "description"}) for i in merged.open_issues
                ],
                "decisions": [
                    d.model_dump(include={"title", "description"}) for d in merged.decisions
                ],
                "next_actions": [
                    a.model_dump(include={"title", "description"}) for a in merged.next_actions
                ],
            },
            "new_source": {"title": source_title, "summary": summary, "text": text},
        }
        output = await self.pipeline.run_stage(
            "context_update", prompts.CONTEXT_UPDATE_PROMPT, payload, ContextUpdateOutput
        )
        merged.open_issues, issue_warnings = _close(
            merged.open_issues, output.resolved_issues, EntityKind.ISSUE, text, "이슈 해결"
        )
        merged.next_actions, action_warnings = _close(
            merged.next_actions, output.completed_actions, EntityKind.TASK, text, "할 일 완료"
        )
        merged.summary = output.summary.strip() or state.summary
        merged.current_state = output.current_state.strip() or state.current_state
        merged.updated_at = datetime.now(UTC)
        # Only this source's own items can be checked against this source's text.
        own = str(source_id)
        warnings = [
            *unverified_refs(
                text,
                [
                    (i.title, i.source_refs)
                    for i in [*merged.open_issues, *merged.decisions, *merged.next_actions]
                    if i.source_id == own
                ],
            ),
            *issue_warnings,
            *action_warnings,
        ]
        return merged, warnings


class ContextStoreRepository(Protocol):
    async def load(self, workspace_id: UUID) -> ContextStoreRecord | None: ...

    async def save(self, record: ContextStoreRecord) -> None: ...

    async def replace_timeline(self, source_id: UUID, rows: list[ContextRecord]) -> None: ...


def state_from_record(record: ContextStoreRecord) -> ContextStoreState:
    return ContextStoreState(
        subject=record.subject,
        summary=record.summary,
        current_state=record.current_state,
        open_issues=[StoreItem.model_validate(i) for i in record.open_issues],
        decisions=[StoreDecision.model_validate(d) for d in record.decisions],
        next_actions=[StoreAction.model_validate(a) for a in record.next_actions],
        source_ids=list(record.source_ids),
        updated_at=record.updated_at,
    )


class ContextStoreService:
    def __init__(self, repository: ContextStoreRepository, updater: ContextStoreUpdater) -> None:
        self.repository = repository
        self.updater = updater

    async def current_decisions(self, workspace_id: UUID) -> list[str]:
        """Titles of decisions nobody has replaced: what a new decision may supersede."""
        record = await self.repository.load(workspace_id)
        return [d.title for d in state_from_record(record).decisions] if record else []

    async def apply(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        source_id: UUID,
        source_title: str,
        subject: str,
        text: str,
        result: ExtractionResult,
    ) -> list[str]:
        record = await self.repository.load(workspace_id)
        state = state_from_record(record) if record else ContextStoreState(subject=subject)
        state.subject = subject
        new_state, warnings = await self.updater.update(
            state, result, source_id=source_id, source_title=source_title, text=text
        )
        record = record or ContextStoreRecord(
            workspace_id=workspace_id, owner_id=owner_id, subject=subject
        )
        record.subject = new_state.subject
        record.summary = new_state.summary
        record.current_state = new_state.current_state
        record.open_issues = [i.model_dump() for i in new_state.open_issues]
        record.decisions = [d.model_dump() for d in new_state.decisions]
        record.next_actions = [a.model_dump() for a in new_state.next_actions]
        record.source_ids = new_state.source_ids
        record.updated_at = new_state.updated_at or datetime.now(UTC)
        await self.repository.save(record)
        await self.repository.replace_timeline(
            source_id,
            timeline_records(
                result, workspace_id=workspace_id, owner_id=owner_id, source_id=source_id
            ),
        )
        return warnings

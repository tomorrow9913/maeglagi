"""Validate an external agent's proposed extraction before any sink is written."""

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from app.modules.agent_workflows.errors import WorkflowError
from app.modules.context_engine.application.analysis import squash
from app.modules.context_engine.application.entity_resolution import normalize_name
from app.modules.context_engine.domain.extraction import ExtractedEvent, ExtractionResult
from app.modules.context_engine.domain.ontology import ContextKind, EntityKind, SourceType
from app.modules.workspaces.infrastructure.models import Source

MAX_EXTRACTION_BYTES = 256_000
MAX_ITEMS_PER_GROUP = 100
MAX_QUOTE_CHARS = 1_200
MAX_FIELD_CHARS = 10_000

_CONTEXT_EVENT_KIND = {
    ContextKind.DECISION: EntityKind.DECISION,
    ContextKind.ISSUE: EntityKind.ISSUE,
    ContextKind.TASK: EntityKind.TASK,
    ContextKind.EVENT: EntityKind.EVENT,
}


def _promote_structured_contexts(result: ExtractionResult) -> ExtractionResult:
    """Keep useful graph facts when an agent puts them only in `contexts`.

    External agents commonly describe a decision as a decision context but omit the matching
    event. The graph, timeline and current-decision store are event-backed, so promote those
    structured contexts deterministically while preserving their grounded source references.
    """
    existing = {
        (event.kind, normalize_name(event.name, event.kind.value)) for event in result.events
    }
    promoted: list[ExtractedEvent] = []
    for context in result.contexts:
        kind = _CONTEXT_EVENT_KIND.get(context.kind)
        if kind is None:
            continue
        key = (kind, normalize_name(context.title, kind.value))
        if not key[1] or key in existing:
            continue
        promoted.append(
            ExtractedEvent(
                name=context.title,
                kind=kind,
                description=context.body,
                occurred_at=context.occurred_at,
                due_at=None,
                supersedes=None,
                source_refs=context.source_refs,
            )
        )
        existing.add(key)
    if promoted:
        result.events.extend(promoted)
    return result


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_fingerprint(source: Source, text: str, directory_snapshot: dict[str, Any]) -> str:
    return _hash(
        [
            source.title,
            text,
            source.review_revision,
            source.association_revision,
            directory_snapshot,
        ]
    )


def context_fingerprint(
    source: Source, text: str, known_decisions: list[str], directory_snapshot: dict[str, Any]
) -> str:
    return _hash([source_fingerprint(source, text, directory_snapshot), sorted(known_decisions)])


def result_fingerprint(result: ExtractionResult) -> str:
    return _hash(result.model_dump(mode="json"))


def validate_extraction(
    supplied: dict[str, Any] | ExtractionResult,
    *,
    source: Source,
    text: str,
    known_decisions: list[str],
) -> ExtractionResult:
    try:
        raw = (
            supplied.model_dump(mode="json") if isinstance(supplied, ExtractionResult) else supplied
        )
        if len(json.dumps(raw, ensure_ascii=False).encode()) > MAX_EXTRACTION_BYTES:
            raise WorkflowError("analysis_too_large", "Analysis is too large", 422)
        result = _promote_structured_contexts(ExtractionResult.model_validate(raw))
    except (TypeError, ValueError, ValidationError) as exc:
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError("invalid_analysis", "Invalid extraction result", 422) from exc

    if source.kind == "meeting" and result.classification.source_type is not SourceType.MEETING:
        raise WorkflowError("invalid_analysis", "Meeting classification is required", 422)
    if any(
        len(group) > MAX_ITEMS_PER_GROUP
        for group in (result.entities, result.events, result.relations, result.contexts)
    ):
        raise WorkflowError("analysis_too_large", "Too many extracted items", 422)

    haystack = squash(text).casefold()
    items = [*result.entities, *result.events, *result.relations, *result.contexts]
    for item in items:
        refs = item.source_refs
        if not refs or any(
            not ref.strip() or len(ref) > MAX_QUOTE_CHARS or squash(ref).casefold() not in haystack
            for ref in refs
        ):
            raise WorkflowError("ungrounded_analysis", "Source quotation is missing", 422)
        if any(
            len(value) > MAX_FIELD_CHARS
            for value in item.model_dump(mode="json").values()
            if isinstance(value, str)
        ):
            raise WorkflowError("analysis_too_large", "Extracted field is too long", 422)
    for entity in result.entities:
        for identifier in entity.identifiers:
            if identifier.casefold().startswith("directory:") or (
                squash(identifier).casefold() not in haystack
            ):
                raise WorkflowError("ungrounded_analysis", "Entity identifier is unverified", 422)

    # Relations contain names, never caller-supplied IDs. Every endpoint must
    # resolve uniquely within this extraction, which is later pinned to one workspace.
    endpoints: dict[tuple[str, str], set[int]] = {}
    for index, item in enumerate([*result.entities, *result.events]):
        for name in [item.name, *(item.aliases if hasattr(item, "aliases") else [])]:
            key = (item.kind.value, normalize_name(name, item.kind.value))
            endpoints.setdefault(key, set()).add(index)
    for relation in result.relations:
        for name in (relation.source, relation.target):
            candidates = {
                index
                for kind in EntityKind
                for index in endpoints.get((kind.value, normalize_name(name, kind.value)), set())
            }
            if len(candidates) != 1:
                raise WorkflowError("invalid_relation", "Relation endpoint is not unique", 422)

    known = {
        normalize_name(name, EntityKind.DECISION.value)
        for name in [
            *known_decisions,
            *(item.name for item in result.events if item.kind is EntityKind.DECISION),
        ]
    }
    for event in result.events:
        if (
            event.supersedes
            and normalize_name(event.supersedes, EntityKind.DECISION.value) not in known
        ):
            raise WorkflowError("invalid_supersession", "Earlier decision is unknown", 422)
    # Model-generated diagnostics are not trusted as server diagnostics.
    result.warnings = []
    result.usage = {}
    return result

"""Validate an external agent's proposed extraction before any sink is written."""

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from app.modules.agent_workflows.errors import WorkflowError
from app.modules.context_engine.application.analysis import squash
from app.modules.context_engine.application.entity_resolution import normalize_name
from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import EntityKind, SourceType
from app.modules.workspaces.infrastructure.models import Source

MAX_EXTRACTION_BYTES = 256_000
MAX_ITEMS_PER_GROUP = 100
MAX_QUOTE_CHARS = 1_200
MAX_FIELD_CHARS = 10_000


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_fingerprint(source: Source, text: str) -> str:
    return _hash(
        [
            source.title,
            text,
            source.review_revision,
            source.association_revision,
            source.confirmed_snapshot,
        ]
    )


def context_fingerprint(source: Source, text: str, known_decisions: list[str]) -> str:
    return _hash([source_fingerprint(source, text), sorted(known_decisions)])


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
        result = ExtractionResult.model_validate(raw)
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
    endpoints: dict[str, set[tuple[str, str]]] = {}
    for item in [*result.entities, *result.events]:
        for name in [item.name, *(item.aliases if hasattr(item, "aliases") else [])]:
            endpoints.setdefault(normalize_name(name, "Event"), set()).add(
                (item.kind.value, item.name)
            )
    for relation in result.relations:
        if any(
            len(endpoints.get(normalize_name(name, "Event"), set())) != 1
            for name in (relation.source, relation.target)
        ):
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

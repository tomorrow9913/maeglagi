"""Attach stable directory IDs only to extracted, source-backed entities."""

from typing import Any
from uuid import UUID

from app.modules.context_engine.application.entity_resolution import (
    normalize_identifier,
    normalize_name,
)
from app.modules.context_engine.domain.extraction import ExtractionResult
from app.modules.context_engine.domain.ontology import EntityKind


def canonicalize_directory_entities(
    result: ExtractionResult, snapshot: dict[str, Any] | None, source_text: str
) -> set[str]:
    # Reserve the directory namespace for IDs attached by this validator. Model
    # text cannot assert ownership of an ID, even if it guesses an existing UUID.
    for entity in result.entities:
        entity.identifiers = [
            value
            for value in entity.identifiers
            if not normalize_identifier(value).startswith("directory:")
        ]
    if not snapshot:
        return set()
    people = snapshot.get("people", [])
    project = snapshot.get("project")
    names: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for person in people:
        for name in [person.get("name"), *person.get("aliases", [])]:
            if isinstance(name, str) and name.strip():
                key = (EntityKind.PERSON.value, normalize_name(name, EntityKind.PERSON.value))
                names.setdefault(key, []).append(person)
    if isinstance(project, dict) and isinstance(project.get("name"), str):
        key = (EntityKind.PROJECT.value, normalize_name(project["name"], EntityKind.PROJECT.value))
        names.setdefault(key, []).append(project)

    renamed: dict[str, str] = {}
    trusted_identifiers: set[str] = set()
    event_names = {item.name for item in result.events}
    for entity in result.entities:
        if entity.kind not in {EntityKind.PERSON, EntityKind.PROJECT}:
            continue
        # The directory alone never creates a participant or project graph node. A quoted
        # source span and an extracted matching name are required before canonicalization.
        if entity.name in event_names:
            continue
        if not any(ref.strip() and ref.strip() in source_text for ref in entity.source_refs):
            continue
        key = (entity.kind.value, normalize_name(entity.name, entity.kind.value))
        candidates = {str(item["id"]): item for item in names.get(key, [])}
        if len(candidates) != 1:
            continue
        directory_id, match = next(iter(candidates.items()))
        labels = [match["name"], *match.get("aliases", [])]
        if not any(
            label and label in ref and ref.strip() in source_text
            for label in labels
            for ref in entity.source_refs
        ):
            continue
        try:
            UUID(directory_id)
        except ValueError:
            continue
        old_name = entity.name
        entity.name = match["name"]
        identifier = f"directory:{entity.kind.value.lower()}:{directory_id}"
        if identifier not in entity.identifiers:
            entity.identifiers.append(identifier)
        trusted_identifiers.add(identifier)
        renamed[old_name] = entity.name
    for relation in result.relations:
        relation.source = renamed.get(relation.source, relation.source)
        relation.target = renamed.get(relation.target, relation.target)
    return trusted_identifiers

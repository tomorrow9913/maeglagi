from pydantic import BaseModel, ConfigDict

from app.modules.context_engine.domain.ontology import (
    ContextKind,
    EntityKind,
    RelationKind,
    SourceType,
)


class StageOutput(BaseModel):
    """Base for provider structured output.

    Strict JSON schema mode requires closed objects with every field required,
    so stage models forbid extras and declare optional values as `X | None`.
    """

    model_config = ConfigDict(extra="forbid")


class ClassificationOutput(StageOutput):
    source_type: SourceType
    language: str
    topics: list[str]


class ExtractedEntity(StageOutput):
    name: str
    kind: EntityKind
    aliases: list[str]
    # Identifying details stated in the source (email, employee id, handle). Empty if none.
    identifiers: list[str]
    source_refs: list[str]


class EntityOutput(StageOutput):
    entities: list[ExtractedEntity]


class ExtractedEvent(StageOutput):
    name: str
    kind: EntityKind
    description: str
    occurred_at: str | None
    due_at: str | None
    source_refs: list[str]


class EventOutput(StageOutput):
    events: list[ExtractedEvent]


class ExtractedRelation(StageOutput):
    source: str
    target: str
    kind: RelationKind
    source_refs: list[str]


class RelationOutput(StageOutput):
    relations: list[ExtractedRelation]


class ExtractedContext(StageOutput):
    kind: ContextKind
    title: str
    body: str
    occurred_at: str | None
    source_refs: list[str]


class ContextOutput(StageOutput):
    contexts: list[ExtractedContext]


class ExtractionResult(BaseModel):
    classification: ClassificationOutput
    entities: list[ExtractedEntity]
    events: list[ExtractedEvent]
    relations: list[ExtractedRelation]
    contexts: list[ExtractedContext]
    warnings: list[str]
    usage: dict[str, int]

from enum import StrEnum


class EntityKind(StrEnum):
    """Entity types fixed by TSK-7. Do not add kinds without team agreement."""

    PERSON = "Person"
    PROJECT = "Project"
    ORGANIZATION = "Organization"
    MEETING = "Meeting"
    DOCUMENT = "Document"
    ISSUE = "Issue"
    TASK = "Task"
    DECISION = "Decision"
    EVENT = "Event"
    TECHNOLOGY = "Technology"


class RelationKind(StrEnum):
    """Relation types fixed by TSK-7. Do not add kinds without team agreement."""

    WORKS_ON = "WORKS_ON"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    MENTIONED_IN = "MENTIONED_IN"
    CREATED = "CREATED"
    ASSIGNED_TO = "ASSIGNED_TO"
    RELATED_TO = "RELATED_TO"
    DECIDED_IN = "DECIDED_IN"
    RESULTED_IN = "RESULTED_IN"
    BLOCKED_BY = "BLOCKED_BY"
    DUE_ON = "DUE_ON"


class ContextKind(StrEnum):
    """Matches the `contexts.kind` values in docs/data-model.md."""

    EVENT = "event"
    DECISION = "decision"
    TASK = "task"
    FACT = "fact"
    SUMMARY = "summary"


class SourceType(StrEnum):
    MEETING = "meeting"
    DECISION_RECORD = "decision_record"
    PLAN = "plan"
    REPORT = "report"
    SPEC = "spec"
    OTHER = "other"


# Stage 3 only produces the entity kinds that describe something happening.
EVENT_STAGE_KINDS = (
    EntityKind.MEETING,
    EntityKind.EVENT,
    EntityKind.DECISION,
    EntityKind.TASK,
    EntityKind.ISSUE,
)

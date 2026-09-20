from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class WorkspaceInfo(WorkflowModel):
    id: UUID
    name: str
    created_at: datetime = Field(serialization_alias="createdAt")


class SourceInfo(WorkflowModel):
    id: UUID
    workspace_id: UUID = Field(serialization_alias="workspaceId")
    title: str
    kind: str
    status: str
    stage: str
    analysis_mode: str = Field(serialization_alias="analysisMode")
    review_state: str | None = Field(serialization_alias="reviewState")
    revision: int
    has_media: bool = Field(serialization_alias="hasMedia")
    content_type: str = Field(serialization_alias="contentType")
    size_bytes: int = Field(serialization_alias="sizeBytes")


class AgentUtterance(WorkflowModel):
    id: str = Field(min_length=1, max_length=80)
    person_id: UUID | None = Field(
        default=None, validation_alias="personId", serialization_alias="personId"
    )
    speaker_name: str = Field(
        min_length=1,
        max_length=120,
        validation_alias="speakerName",
        serialization_alias="speakerName",
    )
    text: str = Field(max_length=10000)
    start_seconds: float | None = Field(
        default=None, ge=0, validation_alias="startSeconds", serialization_alias="startSeconds"
    )
    end_seconds: float | None = Field(
        default=None, ge=0, validation_alias="endSeconds", serialization_alias="endSeconds"
    )

    @model_validator(mode="after")
    def clean(self) -> "AgentUtterance":
        self.id = self.id.strip()
        self.speaker_name = self.speaker_name.strip()
        self.text = self.text.strip()
        if not self.id or not self.speaker_name:
            raise ValueError("Utterance ID and speaker are required")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("Utterance end precedes start")
        return self


class SourceChunkInfo(WorkflowModel):
    id: UUID
    text: str
    start_seconds: float | None = Field(serialization_alias="startSeconds")
    end_seconds: float | None = Field(serialization_alias="endSeconds")


class SourceContent(WorkflowModel):
    source: SourceInfo
    text: str | None
    utterances: list[AgentUtterance]
    chunks: list[SourceChunkInfo]
    storage_path: str | None = Field(serialization_alias="storagePath")


class AnalysisContext(WorkflowModel):
    source: SourceInfo
    text: str
    fingerprint: str
    known_decisions: list[str] = Field(serialization_alias="knownDecisions")
    directory: dict[str, Any]
    extraction_schema: dict[str, Any] = Field(serialization_alias="extractionSchema")
    stage_schemas: dict[str, dict[str, Any]] = Field(serialization_alias="stageSchemas")


class AnalysisSubmission(WorkflowModel):
    source_id: UUID = Field(serialization_alias="sourceId")
    phase: str
    warnings: list[str]
    already_applied: bool = Field(serialization_alias="alreadyApplied")

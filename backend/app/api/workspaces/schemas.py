from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    llm_provider: str = Field(validation_alias="llmProvider")
    llm_api_key: str = Field(min_length=1, validation_alias="llmApiKey")


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    created_at: datetime = Field(serialization_alias="createdAt")
    source_count: int = Field(default=0, serialization_alias="sourceCount")


class SourceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    workspace_id: UUID = Field(serialization_alias="workspaceId")
    kind: str
    title: str
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    size_bytes: int | None = Field(default=None, serialization_alias="sizeBytes")
    duration_seconds: float | None = Field(default=None, serialization_alias="durationSeconds")
    transcript_source: str | None = Field(default=None, serialization_alias="transcriptSource")


class TranscriptSourceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=255)
    duration_seconds: float | None = Field(default=None, ge=0, validation_alias="durationSeconds")


class SimilarChunkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    source_id: UUID = Field(serialization_alias="sourceId")
    position: int
    content: str
    distance: float
    start_seconds: float | None = Field(default=None, serialization_alias="startSeconds")
    end_seconds: float | None = Field(default=None, serialization_alias="endSeconds")


class CredentialInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    api_key: str = Field(min_length=1, validation_alias="apiKey")
    label: str = Field(default="기본", min_length=1, max_length=80)


class CredentialValidation(BaseModel):
    valid: bool
    message: str


class CredentialResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    provider: str
    label: str
    key_hint: str = Field(serialization_alias="keyHint")
    status: str
    is_default: bool = Field(serialization_alias="isDefault")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ContextItemSourceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    kind: str
    title: str
    chunk_id: UUID | None = Field(default=None, serialization_alias="chunkId")


class ContextItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    kind: str
    title: str
    summary: str
    occurred_at: datetime = Field(serialization_alias="occurredAt")
    sources: list[ContextItemSourceResponse]
    # The decision that explicitly replaced this one, when a later source said so.
    superseded_by: UUID | None = Field(default=None, serialization_alias="supersededBy")


class ContextStoreItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    description: str
    source_refs: list[str] = Field(serialization_alias="sourceRefs")
    source_id: str | None = Field(default=None, serialization_alias="sourceId")
    decided_at: str | None = Field(default=None, serialization_alias="decidedAt")
    assignee: str | None = None
    due_at: str | None = Field(default=None, serialization_alias="dueAt")


class ContextStoreResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subject: str
    summary: str
    current_state: str = Field(serialization_alias="currentState")
    open_issues: list[ContextStoreItemResponse] = Field(serialization_alias="openIssues")
    decisions: list[ContextStoreItemResponse]
    next_actions: list[ContextStoreItemResponse] = Field(serialization_alias="nextActions")
    source_ids: list[str] = Field(serialization_alias="sourceIds")
    updated_at: datetime = Field(serialization_alias="updatedAt")

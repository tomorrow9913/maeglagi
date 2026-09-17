from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel


class SourceKind(StrEnum):
    DOCUMENT = "document"
    MEETING = "meeting"


class DocumentSection(SQLModel):
    """One parser-produced unit before it enters the common pipeline."""

    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    heading: str | None = None
    timestamp: datetime | None = None
    author: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("section text must not be blank")
        return value


class TranscriptSegment(SQLModel):
    """One STT-produced utterance before it enters the common pipeline."""

    text: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker: str | None = None
    timestamp: datetime | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("transcript text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranscriptSegment":
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return self


class NormalizedSegment(SQLModel):
    """Canonical segment consumed by chunking, analysis, and retrieval."""

    id: UUID
    position: int = Field(ge=0)
    source: str = Field(min_length=1)
    type: str = Field(min_length=1)
    timestamp: datetime | None = None
    author: str | None = None
    content: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    heading: str | None = None
    speaker: str | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")


class NormalizedSource(SQLModel):
    """Common parser/STT result; downstream code does not depend on providers."""

    source_id: UUID
    workspace_id: UUID
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str | None = None
    segments: list[NormalizedSegment] = Field(default_factory=list)
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source title must not be blank")
        return value

    @model_validator(mode="after")
    def validate_segment_positions(self) -> "NormalizedSource":
        positions = [segment.position for segment in self.segments]
        if positions != list(range(len(self.segments))):
            raise ValueError("segment positions must be contiguous and start at zero")
        return self

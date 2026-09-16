from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, Float, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("source_id", "position", name="uq_chunks_source_position"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    source_id: UUID = Field(foreign_key="sources.id", index=True)
    owner_id: UUID = Field(index=True)
    position: int = Field(ge=0)
    content: str = Field(sa_column=Column(Text, nullable=False))
    start_seconds: float | None = Field(default=None, sa_column=Column(Float))
    end_seconds: float | None = Field(default=None, sa_column=Column(Float))
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(1536), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ContextRecord(SQLModel, table=True):
    __tablename__ = "contexts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    source_id: UUID = Field(foreign_key="sources.id", index=True)
    chunk_id: UUID | None = Field(default=None, foreign_key="chunks.id", index=True)
    owner_id: UUID = Field(index=True)
    kind: str = Field(max_length=40, index=True)
    title: str = Field(max_length=255)
    body: str = Field(sa_column=Column(Text, nullable=False))
    occurred_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True, index=True)
    )
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

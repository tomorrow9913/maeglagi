from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "position", name="uq_chunks_source_position"),
        Index("chunks_workspace_id_idx", "workspace_id"),
        Index("chunks_source_id_idx", "source_id"),
        Index("chunks_owner_id_idx", "owner_id"),
        Index(
            "chunks_embedding_hnsw_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding is not null"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    source_id: UUID = Field(
        sa_column=Column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
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
    __table_args__ = (
        Index("contexts_workspace_id_idx", "workspace_id"),
        Index("contexts_source_id_idx", "source_id"),
        Index("contexts_chunk_id_idx", "chunk_id"),
        Index("contexts_occurred_at_idx", text("occurred_at desc")),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    source_id: UUID = Field(
        sa_column=Column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    )
    chunk_id: UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True),
    )
    owner_id: UUID
    kind: str = Field(max_length=40)
    title: str = Field(max_length=255)
    body: str = Field(sa_column=Column(Text, nullable=False))
    occurred_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, default=dict),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ContextStoreRecord(SQLModel, table=True):
    """The current situation of a project (workspace): what holds now, not how it is structured.

    The graph keeps the structure of the work; this keeps the state. One row per workspace.
    The list columns hold the `ContextStoreState` items as JSON.
    """

    __tablename__ = "context_stores"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_context_stores_workspace"),
        Index("context_stores_owner_id_idx", "owner_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
    subject: str = Field(max_length=255)
    summary: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    current_state: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    open_issues: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    decisions: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    next_actions: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    source_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

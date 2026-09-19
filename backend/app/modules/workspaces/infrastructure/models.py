from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"
    __table_args__ = (Index("workspaces_owner_id_idx", "owner_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID
    name: str = Field(max_length=120)
    # The models the owner chose per job, e.g. {"embedding": {"provider": "openai", "model": ...}}.
    model_settings: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, default=dict)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class WorkspacePerson(SQLModel, table=True):
    __tablename__ = "workspace_people"
    __table_args__ = (Index("workspace_people_workspace_id_idx", "workspace_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
    name: str = Field(max_length=120)
    role: str | None = Field(default=None, max_length=120)
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    archived_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class WorkspaceProject(SQLModel, table=True):
    __tablename__ = "workspace_projects"
    __table_args__ = (Index("workspace_projects_workspace_id_idx", "workspace_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
    name: str = Field(max_length=120)
    goal: str | None = Field(default=None, sa_column=Column(Text))
    description: str | None = Field(default=None, sa_column=Column(Text))
    owner_person_id: UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("workspace_people.id", ondelete="SET NULL"))
    )
    starts_on: date | None = None
    ends_on: date | None = None
    archived_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Source(SQLModel, table=True):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "transcript_source is null or transcript_source in ('server', 'browser')",
            name="ck_sources_transcript_source",
        ),
        CheckConstraint(
            "duration_seconds is null or duration_seconds >= 0",
            name="ck_sources_duration_seconds",
        ),
        CheckConstraint("progress >= 0 and progress <= 1", name="ck_sources_progress"),
        Index("sources_workspace_id_idx", "workspace_id"),
        Index("sources_owner_id_idx", "owner_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
    kind: str = Field(max_length=20)
    title: str = Field(max_length=255)
    object_path: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    content_type: str = Field(max_length=120)
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    transcript_source: str | None = Field(default=None, max_length=20)
    duration_seconds: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    transcript_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    raw_transcript_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    raw_utterances: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    review_utterances: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    review_state: ReviewState | None = Field(
        default=None, sa_column=Column(String(24), nullable=True)
    )
    review_revision: int = Field(default=0)
    project_id: UUID | None = Field(
        default=None, sa_column=Column(ForeignKey("workspace_projects.id", ondelete="SET NULL"))
    )
    confirmed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    confirmed_snapshot: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    content_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: SourceStatus = Field(
        default=SourceStatus.QUEUED, sa_column=Column(String(20), nullable=False)
    )
    processing_stage: ProcessingStage = Field(
        default=ProcessingStage.UPLOADED, sa_column=Column(String(20), nullable=False)
    )
    progress: float = Field(default=0, ge=0, le=1, sa_column=Column(Float, nullable=False))
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProviderCredential(SQLModel, table=True):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "label", name="uq_provider_credential_label"),
        CheckConstraint(
            "vault_secret_id is not null or encrypted_secret is not null",
            name="ck_provider_credentials_has_secret",
        ),
        Index("provider_credentials_workspace_id_idx", "workspace_id"),
        Index(
            "provider_credentials_one_default_idx",
            "workspace_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(
        sa_column=Column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    )
    owner_id: UUID
    provider: str = Field(max_length=40)
    label: str = Field(default="기본", max_length=80)
    vault_secret_id: UUID | None = Field(default=None)
    # Compatibility for pre-Vault credentials. New writes leave this empty.
    encrypted_secret: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    key_hint: str = Field(max_length=8)
    status: str = Field(default="active", max_length=20)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

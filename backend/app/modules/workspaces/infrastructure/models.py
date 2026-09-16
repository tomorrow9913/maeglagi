from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(index=True)
    name: str = Field(max_length=120)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    owner_id: UUID = Field(index=True)
    kind: str = Field(max_length=20)
    title: str = Field(max_length=255)
    object_path: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    content_type: str = Field(max_length=120)
    size_bytes: int
    status: str = Field(default="queued", max_length=20)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProviderCredential(SQLModel, table=True):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "label", name="uq_provider_credential_label"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workspace_id: UUID = Field(foreign_key="workspaces.id", index=True)
    owner_id: UUID = Field(index=True)
    provider: str = Field(max_length=40)
    label: str = Field(default="기본", max_length=80)
    encrypted_secret: str = Field(sa_column=Column(Text, nullable=False))
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

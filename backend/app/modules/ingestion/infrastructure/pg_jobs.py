"""Durable source processing work items, independent of any executor."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlmodel import Field, SQLModel


class ProcessingJob(SQLModel, table=True):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("processing_jobs_ready_idx", "status", "next_run_at"),
        Index("processing_jobs_lease_idx", "status", "lease_expires_at"),
    )

    # One row per source; review confirmation rearms the completed transcription row.
    source_id: UUID = Field(
        sa_column=Column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    )
    status: str = Field(default="pending", sa_column=Column(String(20), nullable=False))
    stage: str = Field(default="source", sa_column=Column(String(32), nullable=False))
    provider_attempts: int = Field(default=0)
    claim_generation: int = Field(default=0)
    lease_owner: UUID | None = Field(default=None)
    lease_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    next_run_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_error: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

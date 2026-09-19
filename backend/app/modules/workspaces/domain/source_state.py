"""String-compatible source workflow values stored in existing text columns."""

from enum import StrEnum


class SourceStatus(StrEnum):
    QUEUED = "queued"
    ENQUEUE_PENDING = "enqueue_pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_AGENT = "awaiting_agent"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReviewState(StrEnum):
    TRANSCRIBING = "transcribing"
    AWAITING_REVIEW = "awaiting_review"
    CONFIRMED = "confirmed"


class ProcessingStage(StrEnum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_AGENT = "awaiting_agent"
    CONFIRMED = "confirmed"
    ANALYZING = "analyzing"
    GRAPHING = "graphing"
    COMPLETED = "completed"

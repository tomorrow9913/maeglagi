"""Stable, provider-independent ingestion contracts."""

from app.modules.ingestion.domain.models import (
    DocumentSection,
    NormalizedSegment,
    NormalizedSource,
    SourceKind,
    TranscriptSegment,
)

__all__ = [
    "DocumentSection",
    "NormalizedSegment",
    "NormalizedSource",
    "SourceKind",
    "TranscriptSegment",
]

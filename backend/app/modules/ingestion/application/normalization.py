from collections.abc import Sequence
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid5

from app.modules.ingestion.domain.models import (
    DocumentSection,
    NormalizedSegment,
    NormalizedSource,
    SourceKind,
    TranscriptSegment,
)

RawSegment = TypeVar("RawSegment", DocumentSection, TranscriptSegment)


class SourceNormalizer(Protocol[RawSegment]):
    kind: str

    def normalize(
        self,
        *,
        source_id: UUID,
        workspace_id: UUID,
        title: str,
        segments: Sequence[RawSegment],
        source: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedSource: ...


def _segment_id(source_id: UUID, position: int) -> UUID:
    """Keep evidence identifiers stable when the same source is normalized again."""

    return uuid5(source_id, f"segment:{position}")


class DocumentNormalizer:
    kind = SourceKind.DOCUMENT

    def normalize(
        self,
        *,
        source_id: UUID,
        workspace_id: UUID,
        title: str,
        segments: Sequence[DocumentSection],
        source: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedSource:
        normalized = [
            NormalizedSegment(
                id=_segment_id(source_id, position),
                position=position,
                source=source or str(source_id),
                type=self.kind,
                timestamp=section.timestamp,
                author=section.author,
                content=section.text,
                page=section.page,
                heading=section.heading,
                metadata=dict(section.metadata_),
            )
            for position, section in enumerate(segments)
        ]
        return NormalizedSource(
            source_id=source_id,
            workspace_id=workspace_id,
            kind=self.kind,
            title=title,
            language=language,
            segments=normalized,
            metadata=dict(metadata or {}),
        )


class TranscriptNormalizer:
    kind = SourceKind.MEETING

    def normalize(
        self,
        *,
        source_id: UUID,
        workspace_id: UUID,
        title: str,
        segments: Sequence[TranscriptSegment],
        source: str | None = None,
        language: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizedSource:
        ordered = sorted(segments, key=lambda segment: (segment.start_seconds, segment.end_seconds))
        normalized = [
            NormalizedSegment(
                id=_segment_id(source_id, position),
                position=position,
                source=source or str(source_id),
                type=self.kind,
                timestamp=segment.timestamp,
                author=segment.speaker,
                content=segment.text,
                speaker=segment.speaker,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                metadata=dict(segment.metadata_),
            )
            for position, segment in enumerate(ordered)
        ]
        return NormalizedSource(
            source_id=source_id,
            workspace_id=workspace_id,
            kind=self.kind,
            title=title,
            language=language,
            segments=normalized,
            metadata=dict(metadata or {}),
        )


class NormalizationService:
    """Routes raw source data to a kind-specific normalizer through one interface."""

    def __init__(self) -> None:
        self._normalizers: dict[str, SourceNormalizer[Any]] = {}
        self.register(DocumentNormalizer())
        self.register(TranscriptNormalizer())

    def register(self, normalizer: SourceNormalizer[Any]) -> None:
        self._normalizers[str(normalizer.kind)] = normalizer

    def normalize(self, kind: SourceKind | str, **kwargs: Any) -> NormalizedSource:
        source_kind = str(kind)
        try:
            normalizer = self._normalizers[source_kind]
        except KeyError as exc:
            raise ValueError(f"no normalizer registered for source kind: {source_kind}") from exc
        return normalizer.normalize(**kwargs)

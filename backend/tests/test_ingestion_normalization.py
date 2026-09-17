from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.domain.models import (
    DocumentSection,
    NormalizedSegment,
    NormalizedSource,
    SourceKind,
    TranscriptSegment,
)


def test_document_sections_are_normalized_without_losing_evidence_metadata() -> None:
    source_id = uuid4()
    service = NormalizationService()

    result = service.normalize(
        SourceKind.DOCUMENT,
        source_id=source_id,
        workspace_id=uuid4(),
        title="  Product brief  ",
        language="ko",
        metadata={"content_type": "application/pdf"},
        segments=[
            DocumentSection(
                text="  First paragraph  ",
                page=2,
                heading="Scope",
                author="Min",
                timestamp=datetime(2026, 9, 15, tzinfo=UTC),
                metadata={"bbox": [1, 2]},
            ),
            DocumentSection(text="Second paragraph", page=3),
        ],
    )

    assert result.kind == SourceKind.DOCUMENT
    assert result.title == "Product brief"
    assert [segment.position for segment in result.segments] == [0, 1]
    assert result.segments[0].source == str(source_id)
    assert result.segments[0].type == "document"
    assert result.segments[0].content == "First paragraph"
    assert result.segments[0].author == "Min"
    assert result.segments[0].timestamp == datetime(2026, 9, 15, tzinfo=UTC)
    assert result.segments[0].page == 2
    assert result.segments[0].heading == "Scope"
    assert result.segments[0].metadata_ == {"bbox": [1, 2]}
    assert (
        result.segments[0].id
        == service.normalize(
            "document",
            source_id=source_id,
            workspace_id=result.workspace_id,
            title=result.title,
            segments=[DocumentSection(text="changed")],
        )
        .segments[0]
        .id
    )


def test_transcript_segments_are_sorted_and_normalized_with_speaker_and_timestamps() -> None:
    result = NormalizationService().normalize(
        "meeting",
        source_id=uuid4(),
        workspace_id=uuid4(),
        title="Weekly sync",
        segments=[
            TranscriptSegment(text="Second", start_seconds=8.0, end_seconds=12.0, speaker="Bob"),
            TranscriptSegment(text="First", start_seconds=1.0, end_seconds=4.5, speaker="Alice"),
        ],
    )

    assert result.kind == SourceKind.MEETING
    assert [segment.content for segment in result.segments] == ["First", "Second"]
    assert result.segments[0].author == "Alice"
    assert result.segments[0].start_seconds == 1.0
    assert result.segments[0].end_seconds == 4.5
    assert result.segments[0].page is None


def test_raw_segments_reject_blank_text_and_invalid_time_ranges() -> None:
    with pytest.raises(ValidationError):
        DocumentSection(text="  ")

    with pytest.raises(ValidationError):
        TranscriptSegment(text="invalid", start_seconds=4, end_seconds=3)


def test_custom_phase_two_source_uses_the_same_pipeline_contract() -> None:
    class SlackNormalizer:
        kind = "slack"

        def normalize(
            self,
            *,
            source_id: UUID,
            workspace_id: UUID,
            title: str,
            segments: list[dict[str, Any]],
            **_: Any,
        ) -> NormalizedSource:
            return NormalizedSource(
                source_id=source_id,
                workspace_id=workspace_id,
                kind=self.kind,
                title=title,
                segments=[
                    NormalizedSegment(
                        id=uuid4(),
                        position=index,
                        source=item["channel"],
                        type=self.kind,
                        timestamp=item["timestamp"],
                        author=item["author"],
                        content=item["content"],
                    )
                    for index, item in enumerate(segments)
                ],
            )

    service = NormalizationService()
    service.register(SlackNormalizer())
    result = service.normalize(
        "slack",
        source_id=uuid4(),
        workspace_id=uuid4(),
        title="project channel",
        segments=[
            {
                "channel": "#maeglagi",
                "timestamp": datetime(2026, 9, 15, tzinfo=UTC),
                "author": "Min",
                "content": "Ship the PoC",
            }
        ],
    )

    assert result.segments[0].model_dump(
        include={"source", "type", "timestamp", "author", "content"}
    ) == {
        "source": "#maeglagi",
        "type": "slack",
        "timestamp": datetime(2026, 9, 15, tzinfo=UTC),
        "author": "Min",
        "content": "Ship the PoC",
    }

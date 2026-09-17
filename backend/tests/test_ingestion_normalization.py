from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.domain.models import DocumentSection, SourceKind, TranscriptSegment


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
                text="  First paragraph  ", page=2, heading="Scope", metadata={"bbox": [1, 2]}
            ),
            DocumentSection(text="Second paragraph", page=3),
        ],
    )

    assert result.kind is SourceKind.DOCUMENT
    assert result.title == "Product brief"
    assert [segment.position for segment in result.segments] == [0, 1]
    assert result.segments[0].text == "First paragraph"
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

    assert result.kind is SourceKind.MEETING
    assert [segment.text for segment in result.segments] == ["First", "Second"]
    assert result.segments[0].speaker == "Alice"
    assert result.segments[0].start_seconds == 1.0
    assert result.segments[0].end_seconds == 4.5
    assert result.segments[0].page is None


def test_raw_segments_reject_blank_text_and_invalid_time_ranges() -> None:
    with pytest.raises(ValidationError):
        DocumentSection(text="  ")

    with pytest.raises(ValidationError):
        TranscriptSegment(text="invalid", start_seconds=4, end_seconds=3)

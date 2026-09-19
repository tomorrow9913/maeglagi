from uuid import uuid4

from app.modules.ingestion.application.chunking import CharacterOverlapChunker
from app.modules.ingestion.application.normalization import NormalizationService
from app.modules.ingestion.domain.models import TranscriptSegment


def test_chunker_preserves_source_position_and_meeting_time_range() -> None:
    source_id = uuid4()
    normalized = NormalizationService().normalize(
        "meeting",
        source_id=source_id,
        workspace_id=uuid4(),
        title="Weekly sync",
        segments=[
            TranscriptSegment(
                text="alpha beta gamma delta epsilon",
                start_seconds=12.0,
                end_seconds=18.5,
            )
        ],
    )

    chunks = CharacterOverlapChunker(size=16, overlap=5).chunk(normalized)

    assert len(chunks) > 1
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.source_id == source_id for chunk in chunks)
    assert all(chunk.start_seconds == 12.0 for chunk in chunks)
    assert all(chunk.end_seconds == 18.5 for chunk in chunks)


def test_chunker_rejects_overlap_that_cannot_advance() -> None:
    try:
        CharacterOverlapChunker(size=10, overlap=10)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("invalid overlap must be rejected")

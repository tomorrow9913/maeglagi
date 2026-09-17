from dataclasses import dataclass
from uuid import UUID

from app.modules.ingestion.domain.models import NormalizedSource


@dataclass(frozen=True, slots=True)
class SourceChunk:
    source_id: UUID
    position: int
    content: str
    start_seconds: float | None = None
    end_seconds: float | None = None


class CharacterOverlapChunker:
    """Deterministic character chunking with evidence-preserving overlap."""

    def __init__(self, size: int = 1200, overlap: int = 200) -> None:
        if size < 1 or overlap < 0 or overlap >= size:
            raise ValueError("chunk size must be positive and overlap smaller than size")
        self.size = size
        self.overlap = overlap

    def chunk(self, source: NormalizedSource) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        for segment in source.segments:
            for content in self._split(segment.content):
                chunks.append(
                    SourceChunk(
                        source_id=source.source_id,
                        position=len(chunks),
                        content=content,
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                    )
                )
        return chunks

    def _split(self, content: str) -> list[str]:
        content = content.strip()
        if not content:
            return []
        parts: list[str] = []
        start = 0
        while start < len(content):
            end = min(start + self.size, len(content))
            if end < len(content):
                boundary = content.rfind(" ", start + self.size // 2, end)
                if boundary > start:
                    end = boundary
            part = content[start:end].strip()
            if part:
                parts.append(part)
            if end >= len(content):
                break
            start = max(end - self.overlap, start + 1)
        return parts

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnswerSource(BaseModel):
    """One piece of evidence, shaped like the frontend's `AnswerSource`."""

    model_config = ConfigDict(populate_by_name=True)

    index: int  # matches the [n] the answer cites
    source_id: UUID = Field(serialization_alias="sourceId")
    chunk_id: UUID = Field(serialization_alias="chunkId")
    kind: str
    title: str
    excerpt: str
    # Where a meeting segment starts (seconds), so the viewer can jump to it. Documents: None.
    timestamp: float | None = None


def sources_event(sources: list[AnswerSource]) -> dict[str, Any]:
    return {
        "type": "sources",
        "sources": [s.model_dump(by_alias=True, exclude_none=True, mode="json") for s in sources],
    }


def token_event(text: str) -> dict[str, Any]:
    return {"type": "token", "text": text}


def done_event() -> dict[str, Any]:
    return {"type": "done"}


def error_event(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}

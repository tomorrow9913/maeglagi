"""Confirmed audio reviews can reach extraction without an embedding connection."""

import json
from typing import Any

import pytest

from app.core.config import Settings
from app.modules.context_engine.application.extraction import ExtractionPipeline
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.ingestion.application.pipeline import IngestionPipeline
from app.modules.ingestion.infrastructure import source_processor
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace
from tests.test_extraction_pipeline import FakeAdapter
from tests.test_source_analysis import FakeTaskSession, architecture_meeting, source


async def test_confirmed_edited_audio_reaches_extraction_without_stt_or_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edited = architecture_meeting().text
    record = source()
    record.object_path = "audio/meeting.mp3"
    record.content_type = "audio/mpeg"
    record.transcript_source = "server"
    record.review_state = "confirmed"
    record.raw_transcript_text = "discarded machine transcript"
    record.transcript_text = edited
    record.review_utterances = [
        {
            "id": "edited-1",
            "speakerName": "담당자",
            "text": edited,
            "startSeconds": 0,
            "endSeconds": 10,
        }
    ]

    class Session(FakeTaskSession):
        def __init__(self) -> None:
            super().__init__(record)
            self.chunks: list[Chunk] = []

        async def get(self, model: Any, identifier: Any) -> Any:
            if model is Workspace:
                return Workspace(id=record.workspace_id, owner_id=record.owner_id, name="회의")
            return record

        async def exec(self, statement: Any) -> Any:
            entity = statement.column_descriptions[0]["entity"]
            if entity is ProviderCredential:
                class NoCredentials:
                    def all(self) -> list[Any]:
                        return []

                return NoCredentials()
            if entity is Chunk:
                class NoVectors:
                    def first(self) -> None:
                        return None

                return NoVectors()
            return await super().exec(statement)

        async def execute(self, statement: Any) -> None:
            pass

        def add(self, item: Any) -> None:
            if isinstance(item, Chunk):
                self.chunks.append(item)

    session = Session()
    adapter = FakeAdapter(architecture_meeting().responses)

    class GraphExtraction:
        async def run(self, db: Any, *, source: Any, text: str) -> list[str]:
            await ExtractionPipeline(adapter, "configured-chat-key", model="chat").extract(
                text, title=source.title
            )
            return []

    async def forbidden_download(*args: Any, **kwargs: Any) -> bytes:
        pytest.fail("confirmed review downloaded its old audio artifact")

    async def forbidden_transcribe(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("confirmed review invoked transcription again")

    pipeline = IngestionPipeline(Settings(_env_file=None))
    monkeypatch.setattr(pipeline, "transcribe", forbidden_transcribe)
    monkeypatch.setattr(source_processor, "session_factory", lambda: session)
    monkeypatch.setattr(source_processor, "IngestionPipeline", lambda: pipeline)
    monkeypatch.setattr(source_processor, "SourceAnalysisService", GraphExtraction)
    monkeypatch.setattr(source_processor, "_download_source", forbidden_download)

    await source_processor._process_source(record.id)

    assert record.status == "succeeded"
    assert session.chunks and all(chunk.embedding is None for chunk in session.chunks)
    assert edited.strip() in " ".join(chunk.content for chunk in session.chunks)
    assert adapter.requests
    assert json.loads(adapter.requests[0].messages[1].content)["text"] == edited
    assert "discarded machine transcript" not in adapter.requests[0].messages[1].content

"""A known missing credential is terminal before Celery's provider retry budget."""

from uuid import uuid4

import pytest

from app.modules.ingestion.infrastructure import tasks
from app.modules.ingestion.infrastructure.source_processor import SafeAttemptError


def test_missing_transcription_credential_is_acknowledged_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    calls: list[tuple] = []

    async def process(identifier, *, final_attempt):
        calls.append((identifier, final_attempt))
        return SafeAttemptError(
            code="missing_capability_credential",
            stage="transcribing",
            error_type="MissingCapabilityCredentialError",
            capability="transcription",
            terminal=True,
        )

    monkeypatch.setattr(tasks, "process_source_attempt", process)
    monkeypatch.setattr(
        tasks.process_source,
        "retry",
        lambda *args, **kwargs: pytest.fail("terminal error retried"),
    )

    assert tasks.process_source.run(str(source_id)) is None
    assert calls == [(source_id, False)]

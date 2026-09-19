"""Sentry capture regression tests with an in-memory transport only."""

import asyncio
import json
import logging
import warnings
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import sentry_sdk
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core import observability
from app.core.config import Settings
from app.middleware.http.request_logging import RequestLoggingMiddleware
from app.modules.ingestion.application.pipeline import (
    IngestionPipeline,
    MissingCapabilityCredentialError,
)
from app.modules.ingestion.infrastructure import pg_executor, source_processor
from app.modules.workspaces.domain.source_state import SourceStatus


@contextmanager
def _captured_sentry():
    events: list[dict] = []
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="sentry_sdk")
        with sentry_sdk.init(
            dsn="http://public@example.test/1",
            transport=events.append,
            integrations=[FastApiIntegration(), StarletteIntegration()],
            traces_sample_rate=0,
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            before_send=observability._redact_sentry_event,
        ):
            yield events


def test_web_observability_configures_safe_capture(monkeypatch) -> None:
    configured = []
    monkeypatch.setattr(observability, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        observability.sentry_sdk, "init", lambda **kwargs: configured.append(kwargs)
    )
    settings = SimpleNamespace(
        log_level="INFO",
        sentry_dsn=SimpleNamespace(get_secret_value=lambda: "http://public@example.test/1"),
        app_env="test",
        app_version="test",
        sentry_traces_sample_rate=0,
    )
    observability.configure_observability(settings, web=True)
    assert configured[0]["include_local_variables"] is False
    assert configured[0]["max_request_body_size"] == "never"
    assert configured[0]["before_send"] is observability._redact_sentry_event
    assert configured[0]["transport"] is observability.SafeHttpTransport


def test_real_http_exception_is_captured_once_with_request_id_and_no_secret() -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")

    @app.get("/failure")
    async def failure() -> None:
        private_value = "synthetic-private-token"
        raise RuntimeError(private_value)

    request_id = "0123456789ab4def8123456789abcdef"
    with _captured_sentry() as events:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/failure", headers={"X-Request-ID": request_id}
        )
    assert response.status_code == 500
    assert len(events) == 1
    event = events[0]
    assert event["tags"]["request_id"] == request_id
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "RuntimeError"
    assert exception["value"] == "Message redacted"
    assert exception["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in exception["stacktrace"]["frames"])
    assert event.get("transaction") == "/failure"
    assert "synthetic-private-token" not in json.dumps(event)


def test_trace_and_route_redaction_keeps_only_validated_metadata() -> None:
    event = {
        "tags": {"provider": "ollama", "request_id": "safe", "private": "secret"},
        "contexts": {
            "trace": {
                "trace_id": "a" * 32,
                "span_id": "b" * 16,
                "parent_span_id": "c" * 16,
                "op": "http.server",
                "status": "internal_error",
                "description": "private-path-secret",
            },
            "response": {"body": "private-body-secret"},
        },
        "transaction": "/workspaces/{workspace_id}/sources/{source_id}",
        "transaction_info": {"source": "route"},
    }
    result = observability._redact_sentry_event(event, {})
    assert result["contexts"] == {
        "trace": {
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "parent_span_id": "c" * 16,
            "op": "http.server",
            "status": "internal_error",
        }
    }
    assert result["transaction"] == "/workspaces/{workspace_id}/sources/{source_id}"
    assert result["tags"]["provider"] == "ollama"
    assert "private" not in json.dumps(result)


def test_raw_url_and_unlisted_provider_are_removed() -> None:
    event = {
        "tags": {"provider": "secret-provider-value"},
        "contexts": {"trace": {"trace_id": "secret", "op": "secret/op"}},
        "transaction": "/sources/private-path-secret",
        "transaction_info": {"source": "url"},
        "request": {"url": "https://example.test/private-path-secret", "method": "GET"},
    }
    result = observability._redact_sentry_event(event, {})
    assert "transaction" not in result
    assert "contexts" not in result
    assert result["tags"] == {}
    assert result["request"] == {"method": "GET"}
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("status,reason", [(400, "status_400"), (413, "status_413")])
def test_transport_status_failure_logs_reason_without_body(caplog, status, reason) -> None:
    transport = observability.SafeHttpTransport.__new__(observability.SafeHttpTransport)
    transport.options = {"send_client_reports": False}
    response = SimpleNamespace(
        status=status,
        headers={},
        data=b"synthetic-provider-response-secret",
    )
    with caplog.at_level(logging.WARNING, logger=observability._transport_logger.name):
        transport._handle_response(response, None)
    assert reason in caplog.text
    assert "synthetic-provider-response-secret" not in caplog.text


def test_transport_network_failure_logs_reason_without_exception(caplog, monkeypatch) -> None:
    transport = observability.SafeHttpTransport.__new__(observability.SafeHttpTransport)
    transport.options = {"send_client_reports": False}
    monkeypatch.setattr(transport, "_update_headers", lambda headers: None)

    def fail_request(*_args):
        raise OSError("synthetic-network-secret")

    monkeypatch.setattr(transport, "_request", fail_request)
    with (
        caplog.at_level(logging.WARNING, logger=observability._transport_logger.name),
        pytest.raises(OSError),
    ):
        transport._send_request(b"payload", headers={}, endpoint_type=None)
    assert "network" in caplog.text
    assert "synthetic-network-secret" not in caplog.text


def test_pg_terminal_event_keeps_safe_location_type_and_stage_without_content() -> None:
    try:
        private_value = "synthetic-provider-response-secret"
        raise RuntimeError(private_value)
    except RuntimeError as exc:
        safe = source_processor._safe_attempt_error(exc, "transcribing")
    source_id = uuid4()
    with _captured_sentry() as events:
        pg_executor._report_terminal_failure(source_id, 4, safe)
    assert len(events) == 1
    event = events[0]
    assert event["tags"]["source_id"] == str(source_id)
    assert event["tags"]["failure_stage"] == "transcribing"
    assert event["tags"]["failure_code"] == "processing_error"
    assert event["tags"]["error_type"] == "RuntimeError"
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "SafeAttemptError"
    assert exception["value"] == "Message redacted"
    assert any(
        frame.get("function")
        == "test_pg_terminal_event_keeps_safe_location_type_and_stage_without_content"
        for frame in exception["stacktrace"]["frames"]
    )
    assert "synthetic-provider-response-secret" not in json.dumps(event)


async def test_missing_capability_credential_stops_retry_with_safe_message(monkeypatch) -> None:
    @asynccontextmanager
    async def held_lock(_source_id):
        yield

    class NoCredentialSession:
        async def get(self, _model, _id):
            return SimpleNamespace(model_settings={})

        async def exec(self, _query):
            return SimpleNamespace(all=lambda: [])

    async def failed_processing(_source_id):
        pipeline = IngestionPipeline(Settings(_env_file=None))
        await pipeline.transcribe(
            NoCredentialSession(),
            source=SimpleNamespace(workspace_id=uuid4(), owner_id=uuid4()),
            audio=b"synthetic-audio",
            filename="meeting.wav",
            content_type="audio/wav",
        )

    updates = []

    async def update_source(_source_id, **kwargs):
        updates.append(kwargs)
        return "transcribing"

    monkeypatch.setattr(source_processor, "_source_execution_lock", held_lock)
    monkeypatch.setattr(source_processor, "_process_source", failed_processing)
    monkeypatch.setattr(source_processor, "_update_source", update_source)
    error = await source_processor.process_source_attempt(uuid4(), final_attempt=False)
    assert isinstance(error, source_processor.SafeAttemptError)
    assert error.terminal
    assert error.code == "missing_capability_credential"
    assert error.capability == "transcription"
    assert error.stage == "transcribing"
    assert updates[0]["status"] == SourceStatus.FAILED
    assert "음성 변환" in updates[0]["error_message"]
    assert "API key" not in str(error)


def test_selected_provider_is_kept_only_from_known_provider_enum() -> None:
    for selected, expected in (("nvidia", "nvidia"), ("unknown-private-provider", None)):
        error = MissingCapabilityCredentialError(
            "synthetic-secret", capability="transcription", providers=(selected,)
        )
        safe = source_processor._safe_attempt_error(error, "transcribing")
        assert safe.provider == expected
        assert "synthetic-secret" not in str(safe)


async def test_pg_executor_fails_typed_configuration_error_on_first_attempt(monkeypatch) -> None:
    source_id = uuid4()
    owner = uuid4()
    safe = source_processor.SafeAttemptError(
        code="missing_capability_credential",
        stage="transcribing",
        error_type="MissingCapabilityCredential",
        capability="transcription",
        terminal=True,
    )
    updates = []
    reports = []

    async def heartbeat(*_args):
        await asyncio.Event().wait()

    async def attempt(_source_id, *, final_attempt):
        assert not final_attempt
        return safe

    async def update(_source_id, _owner, _generation, assignment, parameters=None):
        updates.append((assignment, parameters))
        return True

    monkeypatch.setattr(pg_executor, "_heartbeat", heartbeat)
    monkeypatch.setattr(pg_executor, "process_source_attempt", attempt)
    monkeypatch.setattr(pg_executor, "_fenced_update", update)
    monkeypatch.setattr(
        pg_executor, "_report_terminal_failure", lambda *args: reports.append(args)
    )
    await pg_executor._execute_claim(source_id, owner, 1, 0, 60)
    assert len(updates) == 1
    assert "status = 'failed'" in updates[0][0]
    assert updates[0][1] == {"error": "missing_capability_credential"}
    assert reports == [(source_id, 1, safe)]


def test_http_status_is_kept_as_structured_diagnostic_without_response_body() -> None:
    request = httpx.Request("GET", "https://provider.example/api")
    response = httpx.Response(503, text="private-response-body", request=request)
    with pytest.raises(httpx.HTTPStatusError) as captured:
        response.raise_for_status()
    safe = source_processor._safe_attempt_error(captured.value, "analyzing")
    assert safe.code == "http_status"
    assert safe.http_status == 503
    assert safe.error_type == "HTTPStatusError"
    assert "private-response-body" not in str(safe)

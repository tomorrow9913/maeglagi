"""Shared process logging and Sentry setup for HTTP and job workers."""

import logging
import re

import sentry_sdk
from sentry_sdk.integrations.logging import ignore_logger, ignore_logger_for_sentry_logs
from sentry_sdk.transport import HttpTransport

from app.core.config import Settings
from app.core.logging import configure_logging

_SAFE_EVENT_TAGS = frozenset(
    {
        "request_id",
        "transaction_id",
        "source_id",
        "job_generation",
        "failure_stage",
        "extraction_stage",
        "failure_code",
        "error_type",
        "cause_type",
        "http_status",
        "capability",
        "provider",
    }
)
_SAFE_FAILURE_MESSAGES = {
    "missing_capability_credential": "A provider credential for this capability is required",
}
_SAFE_PROVIDERS = frozenset({"openai", "anthropic", "nvidia", "ollama"})
_SAFE_EXTRACTION_STAGES = frozenset(
    {"classification", "entity", "event", "relation", "context", "context_update"}
)
_TRACE_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
_SPAN_ID = re.compile(r"[0-9a-fA-F]{16}\Z")
_TRACE_OPERATIONS = frozenset({"http.server", "http.client", "db", "task", "queue.process"})
_TRACE_STATUSES = frozenset(
    {
        "ok",
        "cancelled",
        "unknown",
        "invalid_argument",
        "deadline_exceeded",
        "not_found",
        "already_exists",
        "permission_denied",
        "resource_exhausted",
        "failed_precondition",
        "aborted",
        "out_of_range",
        "unimplemented",
        "internal_error",
        "unavailable",
        "data_loss",
        "unauthenticated",
    }
)
_ROUTE = re.compile(r"/[a-zA-Z0-9_/{}/:.-]{0,255}\Z")
_DROP_REASON = re.compile(
    r"(?:status_[0-9]{3}|network|full_queue|self_rate_limits|internal_sdk_error)\Z"
)
_transport_logger = logging.getLogger(f"{__name__}.sentry_transport")


class SafeHttpTransport(HttpTransport):
    """Report delivery failure reasons without echoing relay response bodies."""

    def on_dropped_event(self, reason: str) -> None:
        safe_reason = reason if _DROP_REASON.fullmatch(reason) else "unknown"
        _transport_logger.warning("Sentry event delivery failed: %s", safe_reason)

    def _handle_response(self, response, envelope) -> None:
        self._update_rate_limits(response)
        if response.status == 413:
            self._handle_request_error(
                envelope=envelope, loss_reason="status_413", record_reason="send_error"
            )
        elif response.status == 429:
            self.on_dropped_event("status_429")
        elif response.status >= 300 or response.status < 200:
            self._handle_request_error(envelope=envelope, loss_reason=f"status_{response.status}")


def _redact_sentry_event(event: dict, _hint: dict) -> dict:
    """Keep the failure type and stack locations, never exception text or request data."""
    tags = event.get("tags") or {}
    event["tags"] = {
        key: value
        for key, value in tags.items()
        if key in _SAFE_EVENT_TAGS
        and (key != "provider" or (isinstance(value, str) and value in _SAFE_PROVIDERS))
        and (
            key != "extraction_stage"
            or (isinstance(value, str) and value in _SAFE_EXTRACTION_STAGES)
        )
    }
    safe_message = _SAFE_FAILURE_MESSAGES.get(tags.get("failure_code"), "Message redacted")
    for entry in event.get("exception", {}).get("values", []):
        entry["value"] = (
            safe_message if entry.get("type") == "SafeAttemptError" else "Message redacted"
        )
        for frame in entry.get("stacktrace", {}).get("frames", []):
            for field in ("vars", "context_line", "pre_context", "post_context"):
                frame.pop(field, None)
    contexts = event.get("contexts")
    trace = contexts.get("trace") if isinstance(contexts, dict) else None
    trace = trace if isinstance(trace, dict) else {}
    safe_trace = {}
    for key, pattern in (
        ("trace_id", _TRACE_ID),
        ("span_id", _SPAN_ID),
        ("parent_span_id", _SPAN_ID),
    ):
        value = trace.get(key)
        if isinstance(value, str) and pattern.fullmatch(value):
            safe_trace[key] = value
    for key, allowed in (("op", _TRACE_OPERATIONS), ("status", _TRACE_STATUSES)):
        value = trace.get(key)
        if isinstance(value, str) and value in allowed:
            safe_trace[key] = value
    route = event.get("transaction")
    route_source = (event.get("transaction_info") or {}).get("source")
    safe_route = (
        route
        if route_source == "route" and isinstance(route, str) and _ROUTE.fullmatch(route)
        else None
    )
    for field in (
        "logentry",
        "message",
        "breadcrumbs",
        "extra",
        "contexts",
        "user",
        "fingerprint",
        "culprit",
        "transaction",
        "transaction_info",
    ):
        event.pop(field, None)
    if safe_trace:
        event["contexts"] = {"trace": safe_trace}
    if safe_route:
        event["transaction"] = safe_route
        event["transaction_info"] = {"source": "route"}
    request = event.get("request")
    if request is not None:
        event["request"] = {"method": request["method"]} if "method" in request else {}
    if "exception" not in event:
        event["message"] = "Application event (details redacted)"
    return event


def configure_observability(settings: Settings, *, web: bool = False) -> None:
    configure_logging(settings.log_level)
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return
    ignore_logger(_transport_logger.name)
    ignore_logger_for_sentry_logs(_transport_logger.name)
    integrations = []
    if web:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations = [FastApiIntegration(), StarletteIntegration()]
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.app_env,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=integrations,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=_redact_sentry_event,
        transport=SafeHttpTransport,
    )

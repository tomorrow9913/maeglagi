from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app.core.config import Settings
from app.core.logging import configure_logging
from app.middleware.cors import register_cors_middleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.sentry import initialize_sentry


def register_middlewares(application: FastAPI, settings: Settings) -> None:
    """Register cross-cutting middleware in one deterministic startup location."""

    configure_logging(settings.log_level)
    initialize_sentry(settings)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit,
        storage_uri=settings.rate_limit_storage_uri,
    )
    register_cors_middleware(application, settings)
    application.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")

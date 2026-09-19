import sentry_sdk
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.core.config import Settings
from app.core.logging import configure_logging
from app.middleware.http import RateLimitMiddleware, RequestLoggingMiddleware


def register_middlewares(application: FastAPI, settings: Settings) -> None:
    """Configure observability and register middleware in a deterministic order."""

    configure_logging(settings.log_level)
    _initialize_sentry(settings)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit,
        storage_uri=settings.rate_limit_storage_uri,
    )
    application.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")


def _initialize_sentry(settings: Settings) -> None:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.app_env,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[FastApiIntegration(), StarletteIntegration()],
        send_default_pii=False,
    )

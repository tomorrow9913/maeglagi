from fastapi import FastAPI

from app.core.config import Settings
from app.core.observability import configure_observability
from app.middleware.http import RateLimitMiddleware, RequestLoggingMiddleware


def register_middlewares(application: FastAPI, settings: Settings) -> None:
    """Configure observability and register middleware in a deterministic order."""

    configure_observability(settings, web=True)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit,
        storage_uri=settings.rate_limit_storage_uri,
    )

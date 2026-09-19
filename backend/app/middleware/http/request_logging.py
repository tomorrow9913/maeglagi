from time import perf_counter

import sentry_sdk
import structlog
from asgi_correlation_id import correlation_id
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = correlation_id.get()
        sentry_sdk.set_tag("request_id", request_id or "unknown")
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
        )
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # FastAPI/Sentry captures the actual exception once. Logging only
            # stable fields avoids copying exception messages or request data.
            logger.warning(
                "request.failed",
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise
        logger.info(
            "request.completed",
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return response

from limits import parse
from limits.aio.strategies import FixedWindowRateLimiter
from limits.storage import storage_from_string
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limit: str, storage_uri: str) -> None:
        super().__init__(app)
        self.limit = parse(limit)
        async_storage_uri = (
            storage_uri if storage_uri.startswith("async+") else f"async+{storage_uri}"
        )
        self.limiter = FixedWindowRateLimiter(storage_from_string(async_storage_uri))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS" or request.url.path.endswith("/health"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        if not await self.limiter.hit(self.limit, client):
            return JSONResponse(
                status_code=429,
                content={"detail": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."},
                headers={"Retry-After": str(self.limit.get_expiry())},
            )
        return await call_next(request)

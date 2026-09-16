from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.http import RateLimitMiddleware


def test_request_id_is_preserved_in_response() -> None:
    request_id = "0123456789ab4def8123456789abcdef"

    response = TestClient(app).get("/api/v1/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_rate_limit_middleware_rejects_excess_requests() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(RateLimitMiddleware, limit="1/minute", storage_uri="memory://")

    @limited_app.get("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(limited_app)

    assert client.get("/limited").status_code == 200
    response = client.get("/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"

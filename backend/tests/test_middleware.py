import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app
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


def test_unhandled_error_has_cors_only_for_allowed_origin() -> None:
    allowed = "https://maeglagi-frontend.vercel.app"
    test_app = create_app(Settings(_env_file=None, cors_origins=[allowed]))

    @test_app.get("/broken")
    async def broken() -> None:
        raise RuntimeError("private failure details")

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/broken", headers={"Origin": allowed})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == allowed
    assert response.text == "Internal Server Error"
    assert "private failure details" not in response.text

    rejected = client.get("/broken", headers={"Origin": "https://untrusted.example"})
    assert rejected.status_code == 500
    assert "access-control-allow-origin" not in rejected.headers

    with pytest.raises(RuntimeError, match="private failure details"):
        TestClient(test_app).get("/broken", headers={"Origin": allowed})

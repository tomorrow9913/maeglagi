from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app


def test_auth_requires_bearer_token_when_supabase_is_configured() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )
    try:
        response = TestClient(app).get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {"detail": "Bearer token is required"}


def test_auth_me_accepts_supabase_user_without_email(monkeypatch) -> None:
    user_id = uuid4()
    real_client = httpx.AsyncClient

    def supabase_user(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/v1/user"
        assert request.headers["authorization"] == "Bearer kakao-token"
        return httpx.Response(
            200, json={"id": str(user_id), "user_metadata": {"nickname": "카카오 사용자"}}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(supabase_user), **kwargs),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )
    try:
        response = TestClient(app).get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer kakao-token"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"id": str(user_id), "email": None}

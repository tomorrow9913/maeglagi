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

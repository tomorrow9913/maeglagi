from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Maeglagi API",
        "version": "0.1.0",
    }


def test_auth_endpoint_requires_configuration() -> None:
    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication is not configured"}

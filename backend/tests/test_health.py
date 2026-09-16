from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app, create_app


def test_health() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Maeglagi API",
        "version": "0.1.0",
    }


def test_api_documentation_is_disabled_in_production() -> None:
    client = TestClient(create_app(Settings(app_env="production")))

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_api_documentation_is_available_outside_production() -> None:
    client = TestClient(create_app(Settings(app_env="local")))

    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200

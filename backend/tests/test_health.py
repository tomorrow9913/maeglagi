import importlib

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


def test_readiness_reports_all_storage_roles(monkeypatch) -> None:
    async def healthy_stores():
        return {
            "objectStorage": "ok",
            "postgresql": "ok",
            "vector": "ok",
            "graph": "ok",
        }

    router_module = importlib.import_module("app.api.system.router")
    monkeypatch.setattr(router_module, "check_storage_health", healthy_stores)

    response = TestClient(app).get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "objectStorage": "ok",
            "postgresql": "ok",
            "vector": "ok",
            "graph": "ok",
        },
    }


def test_readiness_is_unavailable_when_a_store_fails(monkeypatch) -> None:
    async def degraded_stores():
        return {
            "objectStorage": "error",
            "postgresql": "ok",
            "vector": "ok",
            "graph": "ok",
        }

    router_module = importlib.import_module("app.api.system.router")
    monkeypatch.setattr(router_module, "check_storage_health", degraded_stores)

    response = TestClient(app).get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["objectStorage"] == "error"


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

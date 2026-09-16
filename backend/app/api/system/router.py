from fastapi import APIRouter, Response, status

from app.api.system.schemas import HealthResponse, ReadinessResponse, StorageChecks
from app.core.config import get_settings
from app.core.storage_health import check_storage_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(service=settings.app_name, version=settings.app_version)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    checks = await check_storage_health()
    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if ready else "degraded",
        checks=StorageChecks.model_validate(checks),
    )

from fastapi import APIRouter

from app.api.system.schemas import HealthResponse
from app.core.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(service=settings.app_name, version=settings.app_version)

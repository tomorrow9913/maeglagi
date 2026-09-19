from app.api.ai.catalog import router as catalog_router
from app.api.ai.models import router as models_router
from app.api.ai.router import router

__all__ = ["catalog_router", "models_router", "router"]

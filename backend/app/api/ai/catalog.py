from fastapi import APIRouter

from app.api.ai.schemas import ProviderCatalogItem
from app.auth import CurrentUser
from app.modules.context_engine.infrastructure.provider_registry import provider_registry

router = APIRouter(prefix="/ai")


@router.get("/providers", response_model=list[ProviderCatalogItem])
async def list_supported_providers(_user: CurrentUser) -> list[ProviderCatalogItem]:
    """Providers the server supports, for choosing one before a workspace exists.

    `configured` and `models` are per-workspace facts, so they are always empty here; the
    workspace-scoped catalog (`/workspaces/{id}/ai/providers`) fills them in.
    """
    return [
        ProviderCatalogItem(
            id=adapter.id,
            display_name=adapter.display_name,
            capabilities=list(adapter.capabilities),
            configured=False,
            models=[],
        )
        for adapter in provider_registry.all()
    ]

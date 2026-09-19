from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.ai.schemas import ProviderCatalogItem
from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.modules.context_engine.infrastructure.provider_registry import provider_registry

router = APIRouter(prefix="/ai")


@router.get("/providers", response_model=list[ProviderCatalogItem])
async def list_supported_providers(
    _user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]
) -> list[ProviderCatalogItem]:
    """Providers the server supports, for choosing one before a workspace exists.

    `configured` and `models` are per-workspace facts, so they are always empty here; the
    workspace-scoped catalog (`/workspaces/{id}/ai/providers`) fills them in. `defaultModels`
    is what the provider preselects per job, so it can be shown as soon as a provider is picked.
    """
    return [
        ProviderCatalogItem(
            id=adapter.id,
            display_name=adapter.display_name,
            capabilities=list(adapter.capabilities),
            configured=False,
            auth_mode="none" if adapter.id == "ollama" else "apiKey",
            models=[],
            default_models=settings.provider_default_models.get(adapter.id, {}),
        )
        for adapter in provider_registry.all()
    ]

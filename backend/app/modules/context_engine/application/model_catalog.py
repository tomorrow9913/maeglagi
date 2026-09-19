from datetime import date
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.credentials import CredentialUnavailableError, resolve_credential_secret
from app.modules.context_engine.application.model_pricing import model_prices
from app.modules.context_engine.application.model_roles import (
    ModelOption,
    ModelRole,
    options_by_role,
)
from app.modules.context_engine.application.provider import ModelInfo, ProviderAdapter
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.context_engine.infrastructure.provider_registry import provider_registry
from app.modules.workspaces.infrastructure.models import ProviderCredential


def live_model_ids(infos: list[ModelInfo], today: date | None = None) -> list[str]:
    """Ids of models the provider has not retired. A shutdown date that has arrived means gone."""
    today = today or date.today()
    return [i.id for i in infos if i.shutdown_date is None or i.shutdown_date > today]


async def models_of(adapter: ProviderAdapter, api_key: str) -> list[str]:
    """What the key can use right now. A provider that cannot answer offers nothing.

    Models the provider itself has already retired are left out, so they are never offered.
    """
    try:
        return live_model_ids(await adapter.list_model_infos(api_key))
    except ProviderError:
        return []


async def options_for_key(provider: str, api_key: str) -> dict[ModelRole, list[ModelOption]]:
    """Model options of a single key, before any workspace exists."""
    adapter = provider_registry.get(provider)
    if adapter is None:
        return options_by_role([])
    return options_by_role([(adapter, await models_of(adapter, api_key))], await model_prices())


async def options_for_workspace(
    session: AsyncSession, workspace_id: UUID, owner_id: UUID, provider: str | None = None
) -> dict[ModelRole, list[ModelOption]]:
    """Models from active keys, optionally limited to the provider being configured."""
    statement = (
        select(ProviderCredential)
        .where(
            ProviderCredential.workspace_id == workspace_id,
            ProviderCredential.owner_id == owner_id,
            ProviderCredential.status == "active",
        )
        .order_by(ProviderCredential.is_default.desc(), ProviderCredential.created_at)
    )
    if provider is not None:
        statement = statement.where(ProviderCredential.provider == provider)
    result = await session.exec(statement)
    listings: list[tuple[ProviderAdapter, list[str]]] = []
    for credential in result.all():
        adapter = provider_registry.get(credential.provider)
        if adapter is None:
            continue
        try:
            api_key = await resolve_credential_secret(session, credential)
        except CredentialUnavailableError:
            continue
        listings.append((adapter, await models_of(adapter, api_key)))
    return options_by_role(listings, await model_prices())


async def has_indexed_chunks(session: AsyncSession, workspace_id: UUID) -> bool:
    """Once anything is embedded, the embedding model is fixed: vectors of two models do not mix."""
    found = await session.exec(select(Chunk.id).where(Chunk.workspace_id == workspace_id).limit(1))
    return found.first() is not None


def recommended_selections(
    options: dict[ModelRole, list[ModelOption]],
) -> dict[str, dict[str, str]]:
    """The first (recommended) option of every role that has one, in storable form."""
    return {role.value: items[0].model_dump() for role, items in options.items() if items}


def with_recommended_defaults(
    chosen: dict[str, Any], options: dict[ModelRole, list[ModelOption]]
) -> dict[str, Any]:
    """`chosen` as it is, plus the recommended model for every job it says nothing about."""
    return {**recommended_selections(options), **chosen}

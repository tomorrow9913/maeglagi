from app.core.api_key_format import api_key_format_error
from app.modules.context_engine.infrastructure.provider_registry import provider_registry


async def validate_provider_credential(
    provider: str, api_key: str, base_url: str | None = None
) -> tuple[bool, str]:
    if error := api_key_format_error(api_key, allow_empty=provider == "ollama"):
        return False, error
    adapter = (
        provider_registry.get(provider, base_url=base_url)
        if provider == "ollama"
        else provider_registry.get(provider)
    )
    if adapter is None:
        return False, "지원하지 않는 provider입니다."
    return await adapter.validate_credential(api_key)

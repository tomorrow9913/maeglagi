from app.modules.context_engine.infrastructure.provider_registry import provider_registry


async def validate_provider_credential(provider: str, api_key: str) -> tuple[bool, str]:
    adapter = provider_registry.get(provider)
    if adapter is None:
        return False, "지원하지 않는 provider입니다."
    return await adapter.validate_credential(api_key)

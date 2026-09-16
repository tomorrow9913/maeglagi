from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.context_engine.infrastructure.provider_adapters import (
    AnthropicAdapter,
    OpenAICompatibleAdapter,
)


class ProviderRegistry:
    def __init__(self, adapters: list[ProviderAdapter]) -> None:
        self._adapters = {adapter.id: adapter for adapter in adapters}

    def get(self, provider: str) -> ProviderAdapter | None:
        return self._adapters.get(provider)

    def all(self) -> list[ProviderAdapter]:
        return list(self._adapters.values())


provider_registry = ProviderRegistry(
    [
        OpenAICompatibleAdapter("openai", "OpenAI", "https://api.openai.com/v1"),
        AnthropicAdapter(),
        OpenAICompatibleAdapter("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
    ]
)

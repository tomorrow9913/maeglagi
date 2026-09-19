from app.core.config import get_settings
from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.context_engine.infrastructure.ollama_adapter import OllamaAdapter
from app.modules.context_engine.infrastructure.provider_adapters import (
    AnthropicAdapter,
    OpenAICompatibleAdapter,
)


class ProviderRegistry:
    def __init__(self, adapters: list[ProviderAdapter]) -> None:
        self._adapters = {adapter.id: adapter for adapter in adapters}

    def get(self, provider: str) -> ProviderAdapter | None:
        if provider == "ollama" and get_settings().ollama_base_url:
            return OllamaAdapter(get_settings().ollama_base_url)
        return self._adapters.get(provider)

    def all(self) -> list[ProviderAdapter]:
        adapters = list(self._adapters.values())
        ollama = self.get("ollama")
        if ollama is not None:
            adapters.append(ollama)
        return adapters


provider_registry = ProviderRegistry(
    [
        OpenAICompatibleAdapter(
            "openai",
            "OpenAI",
            "https://api.openai.com/v1",
            supports_embedding=True,
            supports_structured_output=True,
            supports_transcription=True,
        ),
        AnthropicAdapter(),
        OpenAICompatibleAdapter("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
    ]
)

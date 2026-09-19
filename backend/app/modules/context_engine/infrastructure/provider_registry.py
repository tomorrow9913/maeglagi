from types import SimpleNamespace
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.ollama_endpoint import normalize_ollama_url
from app.modules.context_engine.application.provider import ProviderAdapter
from app.modules.context_engine.infrastructure.ollama_adapter import OllamaAdapter
from app.modules.context_engine.infrastructure.provider_adapters import (
    AnthropicAdapter,
    OpenAICompatibleAdapter,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential


class ProviderRegistry:
    def __init__(self, adapters: list[ProviderAdapter]) -> None:
        self._adapters = {adapter.id: adapter for adapter in adapters}

    def get(self, provider: str, *, base_url: str | None = None) -> ProviderAdapter | None:
        if provider == "ollama":
            settings = get_settings()
            endpoint = base_url or settings.ollama_base_url
            allowed_hosts = list(settings.ollama_allowed_private_hosts)
            if endpoint and base_url is None:
                # Only a legacy row may inherit the administrator endpoint. Trust
                # that exact destination, not arbitrary private user URLs.
                parsed = urlsplit(normalize_ollama_url(endpoint))
                legacy_host = parsed.hostname or ""
                allowed_hosts.append(
                    f"[{legacy_host}]:{parsed.port}"
                    if ":" in legacy_host and parsed.port
                    else f"[{legacy_host}]"
                    if ":" in legacy_host
                    else f"{legacy_host}:{parsed.port}"
                    if parsed.port
                    else legacy_host
                )
            return (
                OllamaAdapter(
                    endpoint,
                    allowed_private_hosts=allowed_hosts,
                    allow_private_network=settings.deployment_mode == "self_hosted",
                )
                if endpoint
                else None
            )
        return self._adapters.get(provider)

    def all(self) -> list[ProviderAdapter]:
        adapters = list(self._adapters.values())
        adapters.append(
            SimpleNamespace(
                id=OllamaAdapter.id,
                display_name=OllamaAdapter.display_name,
                capabilities=OllamaAdapter.capabilities,
            )
        )
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


def adapter_for_credential(credential: ProviderCredential) -> ProviderAdapter | None:
    """Resolve endpoint only for Ollama; other providers keep their shared adapters."""
    provider = credential.provider
    if provider == "ollama":
        return provider_registry.get(provider, base_url=getattr(credential, "base_url", None))
    return provider_registry.get(provider)

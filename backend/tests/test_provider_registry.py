from app.modules.context_engine.infrastructure.provider_registry import provider_registry


def test_registry_exposes_only_registered_providers() -> None:
    assert [adapter.id for adapter in provider_registry.all()] == ["openai", "anthropic", "nvidia"]


def test_nvidia_uses_openai_compatible_capabilities() -> None:
    adapter = provider_registry.get("nvidia")

    assert adapter is not None
    assert adapter.display_name == "NVIDIA NIM"
    assert set(adapter.capabilities) == {"chat", "models"}


def test_unknown_provider_is_not_available() -> None:
    assert provider_registry.get("unknown") is None

from typing import Any

from pydantic import BaseModel, Field

from app.modules.context_engine.application.provider import ChatMessage


class ProviderCatalogItem(BaseModel):
    id: str
    display_name: str = Field(serialization_alias="displayName")
    capabilities: list[str]
    configured: bool
    models: list[str] = Field(default_factory=list)


class ProviderChatRequest(BaseModel):
    provider: str
    model: str
    messages: list[ChatMessage]
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")

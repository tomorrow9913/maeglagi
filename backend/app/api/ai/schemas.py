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


class ProviderEmbeddingRequest(BaseModel):
    provider: str
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")


class ProviderStructuredOutputRequest(BaseModel):
    provider: str
    model: str
    messages: list[ChatMessage]
    schema_name: str = Field(alias="schemaName")
    json_schema: dict[str, Any] = Field(alias="jsonSchema")
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")

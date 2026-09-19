from typing import Any

from pydantic import BaseModel, Field

from app.modules.context_engine.application.provider import ChatMessage


class ProviderCatalogItem(BaseModel):
    id: str
    display_name: str = Field(serialization_alias="displayName")
    capabilities: list[str]
    configured: bool
    auth_mode: str = Field(default="apiKey", serialization_alias="authMode")
    requires_base_url: bool = Field(default=False, serialization_alias="requiresBaseUrl")
    models: list[str] = Field(default_factory=list)
    # The model this provider preselects per job (answer, extraction, embedding, transcription).
    default_models: dict[str, str] = Field(
        default_factory=dict, serialization_alias="defaultModels"
    )


class ProviderChatRequest(BaseModel):
    provider: str
    model: str
    messages: list[ChatMessage]
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    credential_id: str | None = Field(default=None, alias="credentialId")
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")


class ProviderEmbeddingRequest(BaseModel):
    provider: str
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    credential_id: str | None = Field(default=None, alias="credentialId")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")


class ProviderStructuredOutputRequest(BaseModel):
    provider: str
    model: str
    messages: list[ChatMessage]
    schema_name: str = Field(alias="schemaName")
    json_schema: dict[str, Any] = Field(alias="jsonSchema")
    credential_label: str | None = Field(default=None, alias="credentialLabel")
    credential_id: str | None = Field(default=None, alias="credentialId")
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    provider_options: dict[str, Any] = Field(default_factory=dict, alias="providerOptions")

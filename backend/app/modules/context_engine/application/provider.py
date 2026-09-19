from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """What a provider tells us about one model. Providers do not report prices."""

    id: str
    created: datetime | None = None
    # Set by providers that announce retirement (OpenAI does). A retired model is not offered.
    shutdown_date: date | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    text: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str
    dimensions: int | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptionRequest(BaseModel):
    audio: bytes
    filename: str
    content_type: str
    model: str
    language: str | None = None


class TranscriptionSegment(BaseModel):
    text: str
    start_seconds: float
    end_seconds: float
    speaker: str | None = None


class TranscriptionResponse(BaseModel):
    text: str
    model: str
    provider: str
    language: str | None = None
    duration_seconds: float | None = None
    segments: list[TranscriptionSegment] = Field(default_factory=list)


class StructuredOutputRequest(BaseModel):
    messages: list[ChatMessage]
    model: str
    schema_name: str
    json_schema: dict[str, Any]
    temperature: float | None = None
    max_tokens: int | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)


class StructuredOutputResponse(BaseModel):
    data: Any
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderAdapter(Protocol):
    id: str
    display_name: str
    capabilities: tuple[str, ...]

    async def validate_credential(self, api_key: str) -> tuple[bool, str]: ...

    async def list_models(self, api_key: str) -> list[str]: ...

    async def list_model_infos(self, api_key: str) -> list[ModelInfo]: ...

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse: ...

    async def embedding(self, request: EmbeddingRequest, api_key: str) -> EmbeddingResponse: ...

    async def transcribe(
        self, request: TranscriptionRequest, api_key: str
    ) -> TranscriptionResponse: ...

    async def structured_output(
        self, request: StructuredOutputRequest, api_key: str
    ) -> StructuredOutputResponse: ...

    def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]: ...

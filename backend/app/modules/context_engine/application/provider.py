from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel, Field


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


class ProviderAdapter(Protocol):
    async def validate_credential(self, api_key: str) -> tuple[bool, str]: ...

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse: ...

    def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]: ...

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.modules.context_engine.application.provider import ChatRequest, ChatResponse


class ProviderError(RuntimeError):
    pass


class OpenAICompatibleAdapter:
    capabilities = ("chat", "models")

    def __init__(self, provider_id: str, display_name: str, base_url: str) -> None:
        self.id = provider_id
        self.display_name = display_name
        self.base_url = base_url.rstrip("/")

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def validate_credential(self, api_key: str) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers(api_key)
                )
        except httpx.HTTPError:
            return False, "Provider에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
        if response.is_success:
            return True, "사용할 수 있는 API key입니다."
        if response.status_code in {401, 403}:
            return False, "유효하지 않거나 권한이 없는 API key입니다."
        return False, f"Provider가 API key를 확인하지 못했습니다 ({response.status_code})."

    async def list_models(self, api_key: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers(api_key)
                )
        except httpx.HTTPError as exc:
            raise ProviderError("Provider에 연결하지 못했습니다.") from exc
        if not response.is_success:
            raise ProviderError(f"모델 목록을 가져오지 못했습니다 ({response.status_code}).")
        payload = response.json()
        return sorted(
            item["id"] for item in payload.get("data", []) if isinstance(item.get("id"), str)
        )

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
        payload: dict[str, Any] = {
            **request.provider_options,
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(api_key),
                json=payload,
            )
        if not response.is_success:
            raise ProviderError(f"모델 요청에 실패했습니다 ({response.status_code}).")
        body = response.json()
        choice = body.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "")
        usage = {key: int(value) for key, value in body.get("usage", {}).items()}
        return ChatResponse(
            text=text,
            model=body.get("model", request.model),
            provider=self.id,
            usage=usage,
            provider_metadata={"request_id": response.headers.get("x-request-id")},
        )

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        raise NotImplementedError("Streaming adapter는 후속 단계에서 구현합니다.")


class AnthropicAdapter:
    id = "anthropic"
    display_name = "Anthropic"
    capabilities = ("chat", "models")
    base_url = "https://api.anthropic.com/v1"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    async def validate_credential(self, api_key: str) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models?limit=1", headers=self._headers(api_key)
                )
        except httpx.HTTPError:
            return False, "Provider에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
        if response.is_success:
            return True, "사용할 수 있는 API key입니다."
        if response.status_code in {401, 403}:
            return False, "유효하지 않거나 권한이 없는 API key입니다."
        return False, f"Provider가 API key를 확인하지 못했습니다 ({response.status_code})."

    async def list_models(self, api_key: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models?limit=100", headers=self._headers(api_key)
                )
        except httpx.HTTPError as exc:
            raise ProviderError("Provider에 연결하지 못했습니다.") from exc
        if not response.is_success:
            raise ProviderError(f"모델 목록을 가져오지 못했습니다 ({response.status_code}).")
        return sorted(item["id"] for item in response.json().get("data", []))

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
        payload: dict[str, Any] = {
            **request.provider_options,
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "max_tokens": request.max_tokens or 1024,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/messages", headers=self._headers(api_key), json=payload
            )
        if not response.is_success:
            raise ProviderError(f"모델 요청에 실패했습니다 ({response.status_code}).")
        body = response.json()
        text = "".join(block.get("text", "") for block in body.get("content", []))
        usage = {key: int(value) for key, value in body.get("usage", {}).items()}
        return ChatResponse(
            text=text, model=body.get("model", request.model), provider=self.id, usage=usage
        )

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        raise NotImplementedError("Streaming adapter는 후속 단계에서 구현합니다.")

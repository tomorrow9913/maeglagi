import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.modules.context_engine.application.provider import (
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ModelInfo,
    StructuredOutputRequest,
    StructuredOutputResponse,
    TranscriptionRequest,
    TranscriptionResponse,
    TranscriptionSegment,
)


class ProviderError(RuntimeError):
    pass


class ProviderCapabilityError(ProviderError):
    pass


def _parse_date(value: Any) -> date | None:
    """A provider's date field: ISO date or datetime string. Anything else is unknown."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_openai_model(item: Any) -> ModelInfo | None:
    """One entry of an OpenAI-style `/models` list: id, created (epoch), shutdown_date."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return None
    created = item.get("created")
    return ModelInfo(
        id=item["id"],
        created=datetime.fromtimestamp(created, UTC) if isinstance(created, int) else None,
        shutdown_date=_parse_date(item.get("shutdown_date")),
    )


def parse_anthropic_model(item: Any) -> ModelInfo | None:
    """One entry of Anthropic's `/models` list: id and created_at (RFC 3339)."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        return None
    created_at = item.get("created_at")
    try:
        created = datetime.fromisoformat(created_at) if isinstance(created_at, str) else None
    except ValueError:
        created = None
    return ModelInfo(id=item["id"], created=created)


class OpenAICompatibleAdapter:
    def __init__(
        self,
        provider_id: str,
        display_name: str,
        base_url: str,
        *,
        supports_embedding: bool = False,
        supports_structured_output: bool = False,
        supports_transcription: bool = False,
    ) -> None:
        self.id = provider_id
        self.display_name = display_name
        self.base_url = base_url.rstrip("/")
        self._supports_embedding = supports_embedding
        self._supports_structured_output = supports_structured_output
        self._supports_transcription = supports_transcription
        capabilities = ["chat"]
        if supports_embedding:
            capabilities.append("embedding")
        if supports_structured_output:
            capabilities.append("structuredOutput")
        if supports_transcription:
            capabilities.append("transcription")
        capabilities.append("models")
        self.capabilities = tuple(capabilities)

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

    async def list_model_infos(self, api_key: str) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models", headers=self._headers(api_key)
                )
        except httpx.HTTPError as exc:
            raise ProviderError("Provider에 연결하지 못했습니다.") from exc
        if not response.is_success:
            raise ProviderError(f"모델 목록을 가져오지 못했습니다 ({response.status_code}).")
        parsed = (parse_openai_model(item) for item in response.json().get("data", []))
        return [info for info in parsed if info is not None]

    async def list_models(self, api_key: str) -> list[str]:
        return sorted(info.id for info in await self.list_model_infos(api_key))

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

    async def embedding(self, request: EmbeddingRequest, api_key: str) -> EmbeddingResponse:
        if not self._supports_embedding:
            raise ProviderCapabilityError(f"{self.display_name}은 embedding을 지원하지 않습니다.")
        payload: dict[str, Any] = {
            **request.provider_options,
            "model": request.model,
            "input": request.input,
        }
        if request.dimensions is not None:
            payload["dimensions"] = request.dimensions
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(api_key),
                json=payload,
            )
        if not response.is_success:
            raise ProviderError(f"임베딩 요청에 실패했습니다 ({response.status_code}).")
        body = response.json()
        items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        usage = {key: int(value) for key, value in body.get("usage", {}).items()}
        return EmbeddingResponse(
            embeddings=[item["embedding"] for item in items],
            model=body.get("model", request.model),
            provider=self.id,
            usage=usage,
            provider_metadata={"request_id": response.headers.get("x-request-id")},
        )

    async def transcribe(
        self, request: TranscriptionRequest, api_key: str
    ) -> TranscriptionResponse:
        if not self._supports_transcription:
            raise ProviderCapabilityError(
                f"{self.display_name}은 transcription을 지원하지 않습니다."
            )
        data = {"model": request.model, "response_format": "verbose_json"}
        if request.language:
            data["language"] = request.language
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files={"file": (request.filename, request.audio, request.content_type)},
            )
        if not response.is_success:
            raise ProviderError(f"음성 인식 요청에 실패했습니다 ({response.status_code}).")
        body = response.json()
        segments = [
            TranscriptionSegment(
                text=item.get("text", "").strip(),
                start_seconds=float(item.get("start", 0)),
                end_seconds=float(item.get("end", item.get("start", 0))),
            )
            for item in body.get("segments", [])
            if item.get("text", "").strip()
        ]
        text_value = str(body.get("text", "")).strip()
        if not text_value:
            raise ProviderError("음성 인식 결과가 비어 있습니다.")
        return TranscriptionResponse(
            text=text_value,
            model=request.model,
            provider=self.id,
            language=body.get("language"),
            duration_seconds=body.get("duration"),
            segments=segments,
        )

    async def structured_output(
        self, request: StructuredOutputRequest, api_key: str
    ) -> StructuredOutputResponse:
        if not self._supports_structured_output:
            raise ProviderCapabilityError(
                f"{self.display_name}은 structuredOutput을 지원하지 않습니다."
            )
        payload: dict[str, Any] = {
            **request.provider_options,
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            },
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
            raise ProviderError(f"구조화 출력 요청에 실패했습니다 ({response.status_code}).")
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            data = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("Provider가 유효한 JSON 응답을 반환하지 않았습니다.") from exc
        usage = {key: int(value) for key, value in body.get("usage", {}).items()}
        return StructuredOutputResponse(
            data=data,
            model=body.get("model", request.model),
            provider=self.id,
            usage=usage,
            provider_metadata={"request_id": response.headers.get("x-request-id")},
        )

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        """Yield the answer text as the provider produces it (server-sent `data:` lines)."""
        payload: dict[str, Any] = {
            **request.provider_options,
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "stream": True,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(30, read=120)) as client,
                client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(api_key),
                    json=payload,
                ) as response,
            ):
                if not response.is_success:
                    await response.aread()
                    raise ProviderError(f"모델 요청에 실패했습니다 ({response.status_code}).")
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # keep-alive or a malformed frame: skip it, keep streaming
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise ProviderError("Provider에 연결하지 못했습니다.") from exc


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

    async def list_model_infos(self, api_key: str) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/models?limit=100", headers=self._headers(api_key)
                )
        except httpx.HTTPError as exc:
            raise ProviderError("Provider에 연결하지 못했습니다.") from exc
        if not response.is_success:
            raise ProviderError(f"모델 목록을 가져오지 못했습니다 ({response.status_code}).")
        parsed = (parse_anthropic_model(item) for item in response.json().get("data", []))
        return [info for info in parsed if info is not None]

    async def list_models(self, api_key: str) -> list[str]:
        return sorted(info.id for info in await self.list_model_infos(api_key))

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

    async def embedding(self, request: EmbeddingRequest, api_key: str) -> EmbeddingResponse:
        raise ProviderCapabilityError("Anthropic은 embedding을 지원하지 않습니다.")

    async def transcribe(
        self, request: TranscriptionRequest, api_key: str
    ) -> TranscriptionResponse:
        raise ProviderCapabilityError("Anthropic은 transcription을 지원하지 않습니다.")

    async def structured_output(
        self, request: StructuredOutputRequest, api_key: str
    ) -> StructuredOutputResponse:
        raise ProviderCapabilityError("Anthropic structuredOutput은 아직 구현되지 않았습니다.")

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        raise NotImplementedError("Streaming adapter는 후속 단계에서 구현합니다.")

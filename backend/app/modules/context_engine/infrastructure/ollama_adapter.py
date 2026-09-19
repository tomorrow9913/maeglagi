"""Native Ollama API adapter for an administrator configured local server."""

import json
import math
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

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
)
from app.modules.context_engine.infrastructure.provider_adapters import (
    ProviderCapabilityError,
    ProviderError,
    UnsupportedStructuredFormatError,
)


class OllamaAdapter:
    id = "ollama"
    display_name = "Ollama (local)"
    capabilities = ("chat", "embedding", "structuredOutput", "models")

    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OLLAMA_BASE_URL must be an HTTP server address")
        if parsed.hostname in {"ollama.com", "www.ollama.com"}:
            raise ValueError("OLLAMA_BASE_URL must point to a local Ollama server")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_BASE_URL must not include credentials or parameters")
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path}"

    @staticmethod
    def _local_name(name: object) -> bool:
        return isinstance(name, str) and bool(name) and not name.lower().endswith(":cloud")

    async def _tags(self, client: httpx.AsyncClient) -> list[str]:
        try:
            response = await client.get(self._url("tags"))
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Ollama 서버의 로컬 모델 목록을 가져오지 못했습니다.") from exc
        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            raise ProviderError("Ollama 모델 목록이 유효하지 않습니다.")
        return sorted(
            {
                name
                for item in models
                if isinstance(item, dict)
                if self._local_name(name := item.get("name"))
            }
        )

    @staticmethod
    def _is_local_details(details: dict[str, Any]) -> bool:
        capabilities = details.get("capabilities")
        return (
            not details.get("remote_host")
            and not details.get("remote_model")
            and isinstance(capabilities, list)
            and all(isinstance(item, str) for item in capabilities)
            and not any(item.lower() == "cloud" for item in capabilities)
        )

    async def _show(self, client: httpx.AsyncClient, model: str) -> dict[str, Any]:
        try:
            response = await client.post(self._url("show"), json={"model": model})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Ollama 모델 정보를 확인하지 못했습니다.") from exc
        if not isinstance(body, dict):
            raise ProviderError("Ollama 모델 정보가 유효하지 않습니다.")
        return body

    async def _require_local_model(self, client: httpx.AsyncClient, model: str) -> None:
        if not self._local_name(model) or model not in await self._tags(client):
            raise ProviderError("설치된 로컬 Ollama 모델만 사용할 수 있습니다.")
        if not self._is_local_details(await self._show(client, model)):
            raise ProviderError("원격 Ollama 모델은 사용할 수 없습니다.")

    async def validate_credential(self, api_key: str) -> tuple[bool, str]:
        if api_key:
            return False, "Ollama 로컬 연결에는 API key를 입력하지 않습니다."
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await self._tags(client)
        except ProviderError:
            return False, "Ollama 서버에 연결하지 못했습니다. 관리자 설정을 확인해 주세요."
        return True, "Ollama 로컬 서버에 연결되었습니다."

    async def list_model_infos(self, api_key: str) -> list[ModelInfo]:
        infos: list[ModelInfo] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=120)) as client:
            for name in await self._tags(client):
                try:
                    details = await self._show(client, name)
                except ProviderError:
                    continue
                if not self._is_local_details(details):
                    continue
                capabilities = details["capabilities"]
                roles: list[str] = []
                if "completion" in capabilities:
                    roles.extend(("answer", "extraction"))
                if "embedding" in capabilities:
                    # Model metadata alone cannot establish 1536-dimension output.
                    try:
                        result = await self._embed(client, name, "dimension probe", 1536)
                    except ProviderError:
                        pass
                    else:
                        if len(result) == 1 and len(result[0]) == 1536:
                            roles.append("embedding")
                if roles:
                    infos.append(ModelInfo(id=name, roles=tuple(roles)))
        return infos

    async def list_models(self, api_key: str) -> list[str]:
        return [info.id for info in await self.list_model_infos(api_key)]

    @staticmethod
    def _options(request: ChatRequest | StructuredOutputRequest) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        return options

    def _chat_payload(
        self, request: ChatRequest | StructuredOutputRequest, *, stream: bool
    ) -> dict[str, Any]:
        # Provider options cannot override the model, messages, streaming, or schema.
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            "stream": stream,
            "options": self._options(request),
        }
        if isinstance(request, StructuredOutputRequest):
            payload["format"] = request.json_schema
        return payload

    async def _post_chat(self, request: ChatRequest | StructuredOutputRequest) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=120)) as client:
                await self._require_local_model(client, request.model)
                response = await client.post(
                    self._url("chat"), json=self._chat_payload(request, stream=False)
                )
                if not response.is_success:
                    if isinstance(request, StructuredOutputRequest) and response.status_code == 400:
                        raise UnsupportedStructuredFormatError(
                            "이 모델은 native JSON schema 형식을 지원하지 않습니다."
                        )
                    raise ProviderError(
                        f"Ollama 모델 요청에 실패했습니다 ({response.status_code})."
                    )
                body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Ollama 서버에 연결하지 못했습니다.") from exc
        if not isinstance(body, dict) or not isinstance(body.get("message"), dict):
            raise ProviderError("Ollama 응답이 유효하지 않습니다.")
        return body

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
        body = await self._post_chat(request)
        content = body["message"].get("content")
        if not isinstance(content, str):
            raise ProviderError("Ollama 응답이 유효하지 않습니다.")
        return ChatResponse(
            text=content,
            model=body.get("model", request.model),
            provider=self.id,
            usage={
                k: body[k]
                for k in ("prompt_eval_count", "eval_count")
                if isinstance(body.get(k), int)
            },
            provider_metadata={"done_reason": body.get("done_reason")},
        )

    async def structured_output(
        self, request: StructuredOutputRequest, api_key: str
    ) -> StructuredOutputResponse:
        body = await self._post_chat(request)
        content = body["message"].get("content")
        try:
            data = json.loads(content)
        except (ValueError, TypeError) as exc:
            raise ProviderError("Ollama가 유효한 JSON 응답을 반환하지 않았습니다.") from exc
        return StructuredOutputResponse(
            data=data, model=body.get("model", request.model), provider=self.id
        )

    async def _embed(
        self, client: httpx.AsyncClient, model: str, input_value: str | list[str], dimensions: int
    ) -> list[list[float]]:
        try:
            response = await client.post(
                self._url("embed"),
                json={
                    "model": model,
                    "input": input_value,
                    "dimensions": dimensions,
                    "truncate": False,
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ProviderError("Ollama 임베딩 요청에 실패했습니다.") from exc
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or any(
            not isinstance(v, list)
            or len(v) != dimensions
            or any(
                isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
                for x in v
            )
            for v in vectors
        ):
            raise ProviderError("Ollama 임베딩 차원이 Vector Store schema와 다릅니다.")
        return vectors

    async def embedding(self, request: EmbeddingRequest, api_key: str) -> EmbeddingResponse:
        if request.dimensions not in (None, 1536):
            raise ProviderError("Ollama 임베딩은 1536차원만 사용할 수 있습니다.")
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=120)) as client:
            await self._require_local_model(client, request.model)
            vectors = await self._embed(client, request.model, request.input, 1536)
        expected = 1 if isinstance(request.input, str) else len(request.input)
        if len(vectors) != expected:
            raise ProviderError("Ollama 임베딩 응답 개수가 입력 개수와 다릅니다.")
        return EmbeddingResponse(embeddings=vectors, model=request.model, provider=self.id)

    async def transcribe(
        self, request: TranscriptionRequest, api_key: str
    ) -> TranscriptionResponse:
        raise ProviderCapabilityError("Ollama는 음성 인식을 지원하지 않습니다.")

    async def stream(self, request: ChatRequest, api_key: str) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=120)) as client:
                await self._require_local_model(client, request.model)
                async with client.stream(
                    "POST", self._url("chat"), json=self._chat_payload(request, stream=True)
                ) as response:
                    if not response.is_success:
                        raise ProviderError(
                            f"Ollama 모델 요청에 실패했습니다 ({response.status_code})."
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except ValueError as exc:
                            raise ProviderError("Ollama 스트림이 유효하지 않습니다.") from exc
                        if not isinstance(chunk, dict):
                            raise ProviderError("Ollama 스트림이 유효하지 않습니다.")
                        if chunk.get("error"):
                            raise ProviderError("Ollama 스트리밍 중 오류가 발생했습니다.")
                        message = chunk.get("message")
                        if message is not None and not isinstance(message, dict):
                            raise ProviderError("Ollama 스트림이 유효하지 않습니다.")
                        content = (message or {}).get("content")
                        if content:
                            if not isinstance(content, str):
                                raise ProviderError("Ollama 스트림이 유효하지 않습니다.")
                            yield content
                        if chunk.get("done") is True:
                            return
                    raise ProviderError("Ollama 응답 스트림이 완료 전에 종료됐습니다.")
        except httpx.HTTPError as exc:
            raise ProviderError("Ollama 서버에 연결하지 못했습니다.") from exc

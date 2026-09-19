import json
from typing import Any

import pytest

from app.modules.context_engine.application.extraction import (
    ExtractionError,
    ExtractionPipeline,
)
from app.modules.context_engine.application.provider import (
    ChatRequest,
    ChatResponse,
    StructuredOutputRequest,
    StructuredOutputResponse,
)
from app.modules.context_engine.domain.ontology import EntityKind, RelationKind
from app.modules.context_engine.infrastructure.provider_adapters import (
    ProviderError,
    UnsupportedStructuredFormatError,
)

STAGES = ["classification", "entity", "event", "relation", "context"]

RESPONSES: dict[str, dict[str, Any]] = {
    "classification": {"source_type": "meeting", "language": "ko", "topics": ["출시 일정"]},
    "entity": {
        "entities": [
            {
                "name": "김민수",
                "kind": "Person",
                "aliases": ["민수"],
                "identifiers": [],
                "source_refs": ["민수가 말했다"],
            },
            {
                "name": "맥락이",
                "kind": "Project",
                "aliases": [],
                "identifiers": [],
                "source_refs": ["맥락이 프로젝트"],
            },
        ]
    },
    "event": {
        "events": [
            {
                "name": "출시 일정 확정",
                "kind": "Decision",
                "description": "9월 말 출시로 확정",
                "occurred_at": "2026-09-14",
                "due_at": None,
                "supersedes": None,
                "source_refs": ["9월 말 출시로 하기로 했다"],
            }
        ]
    },
    "relation": {
        "relations": [
            {
                "source": "김민수",
                "target": "맥락이",
                "kind": "WORKS_ON",
                "valid_from": None,
                "valid_to": None,
                "source_refs": ["민수가 맥락이를 맡는다"],
            },
            {
                "source": "김민수",
                "target": "없는 개체",
                "kind": "CREATED",
                "valid_from": None,
                "valid_to": None,
                "source_refs": ["환각"],
            },
        ]
    },
    "context": {
        "contexts": [
            {
                "kind": "decision",
                "title": "출시 일정 확정",
                "body": "9월 말 출시로 확정했다.",
                "occurred_at": "2026-09-14",
                "source_refs": ["9월 말 출시로 하기로 했다"],
            }
        ]
    },
}


class FakeAdapter:
    id = "fake"
    display_name = "Fake"
    capabilities = ("chat", "structuredOutput")

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or RESPONSES
        self.requests: list[StructuredOutputRequest] = []

    async def structured_output(
        self, request: StructuredOutputRequest, api_key: str
    ) -> StructuredOutputResponse:
        self.requests.append(request)
        stage = request.schema_name.removeprefix("extraction_")
        data = self.responses[stage]
        if isinstance(data, Exception):
            raise data
        return StructuredOutputResponse(
            data=data,
            model=request.model,
            provider="fake",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


class ChatAdapter:
    display_name = "Chat only"
    capabilities = ("chat", "models")

    def __init__(self, provider: str = "anthropic", overrides: dict[str, list[str]] | None = None):
        self.id = provider
        self.overrides = overrides or {}
        self.requests: list[ChatRequest] = []
        self.attempts: dict[str, int] = {}

    async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
        assert api_key == "key"
        self.requests.append(request)
        # A correction repeats the same stage; otherwise the next stage advances.
        stage = (
            next(reversed(self.attempts))
            if len(request.messages) == 4
            else STAGES[len(self.attempts)]
        )
        attempt = self.attempts.get(stage, 0)
        self.attempts[stage] = attempt + 1
        outputs = self.overrides.get(stage, [])
        answer = outputs[attempt] if attempt < len(outputs) else json.dumps(RESPONSES[stage])
        return ChatResponse(
            text=answer,
            model=request.model,
            provider=self.id,
            usage={"completion_tokens": 5},
        )


def pipeline(adapter: FakeAdapter) -> ExtractionPipeline:
    return ExtractionPipeline(adapter, "key", model="test-model")  # type: ignore[arg-type]


async def test_runs_five_separate_stages_in_order() -> None:
    adapter = FakeAdapter()

    result = await pipeline(adapter).extract("회의 본문", title="주간 회의")

    assert [r.schema_name.removeprefix("extraction_") for r in adapter.requests] == STAGES
    assert len({r.messages[0].content for r in adapter.requests}) == 5
    assert result.entities[0].kind is EntityKind.PERSON
    assert result.events[0].kind is EntityKind.DECISION
    assert result.usage == {"prompt_tokens": 50, "completion_tokens": 25}


async def test_every_stage_forces_a_closed_json_schema() -> None:
    adapter = FakeAdapter()

    await pipeline(adapter).extract("본문")

    for request in adapter.requests:
        assert request.json_schema["additionalProperties"] is False
        assert request.temperature == 0.0


async def test_later_stages_receive_validated_earlier_output() -> None:
    adapter = FakeAdapter()

    await pipeline(adapter).extract("본문")

    relation_input = json.loads(adapter.requests[3].messages[1].content)
    assert [item["name"] for item in relation_input["entities"]] == ["김민수", "맥락이"]
    assert relation_input["events"][0]["name"] == "출시 일정 확정"
    context_input = json.loads(adapter.requests[4].messages[1].content)
    assert [item["kind"] for item in context_input["relations"]] == ["WORKS_ON"]


async def test_relations_to_unknown_entities_are_dropped_with_warning() -> None:
    result = await pipeline(FakeAdapter()).extract("본문")

    assert [relation.kind for relation in result.relations] == [RelationKind.WORKS_ON]
    assert len(result.warnings) == 1
    assert "없는 개체" in result.warnings[0]


async def test_kind_outside_the_ontology_fails_the_stage() -> None:
    bad = {
        **RESPONSES,
        "entity": {"entities": [{**RESPONSES["entity"]["entities"][0], "kind": "Robot"}]},
    }

    with pytest.raises(ExtractionError) as error:
        await pipeline(FakeAdapter(bad)).extract("본문")

    assert error.value.stage == "entity"


async def test_provider_error_is_reported_with_its_stage() -> None:
    failing = {**RESPONSES, "event": ProviderError("boom")}
    adapter = FakeAdapter(failing)

    with pytest.raises(ExtractionError) as error:
        await pipeline(adapter).extract("본문")

    assert error.value.stage == "event"
    assert len(adapter.requests) == 3


def test_provider_without_chat_or_structured_output_is_rejected() -> None:
    adapter = FakeAdapter()
    adapter.capabilities = ("models",)

    with pytest.raises(ExtractionError):
        pipeline(adapter)


@pytest.mark.parametrize("provider", ["anthropic", "nvidia"])
async def test_chat_only_provider_extracts_validated_stages(provider: str) -> None:
    adapter = ChatAdapter(provider)

    result = await ExtractionPipeline(adapter, "key", model="chat-model").extract("본문")  # type: ignore[arg-type]

    assert len(adapter.requests) == 5
    assert result.usage == {"completion_tokens": 25}
    assert result.entities[0].name == "김민수"
    assert "JSON Schema" in adapter.requests[0].messages[0].content
    assert all(request.max_tokens == 4096 for request in adapter.requests)


async def test_malformed_chat_response_gets_one_corrective_retry() -> None:
    adapter = ChatAdapter(overrides={"classification": ["```json\n{}\n```"]})

    result = await ExtractionPipeline(adapter, "key", model="chat-model").extract("본문")  # type: ignore[arg-type]

    assert result.classification.language == "ko"
    assert len(adapter.requests) == 6
    assert len(adapter.requests[1].messages) == 4


async def test_invalid_chat_schema_is_rejected_after_one_retry() -> None:
    adapter = ChatAdapter(overrides={"classification": ["{}", "{}"]})

    with pytest.raises(ExtractionError, match="스키마") as error:
        await ExtractionPipeline(adapter, "key", model="chat-model").extract("본문")  # type: ignore[arg-type]

    assert error.value.stage == "classification"
    assert len(adapter.requests) == 2


async def test_native_format_rejection_falls_back_to_chat_for_that_stage() -> None:
    class MixedAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()

        async def structured_output(
            self, request: StructuredOutputRequest, api_key: str
        ) -> StructuredOutputResponse:
            if request.schema_name == "extraction_entity":
                self.requests.append(request)
                raise UnsupportedStructuredFormatError("unsupported format")
            return await super().structured_output(request, api_key)

        async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
            return ChatResponse(
                text=json.dumps(RESPONSES["entity"]), model=request.model, provider="fake"
            )

    adapter = MixedAdapter()
    result = await pipeline(adapter).extract("본문")

    assert len(adapter.requests) == 5
    assert result.entities[0].name == "김민수"


@pytest.mark.parametrize(
    ("metadata", "message"),
    [({"finish_reason": "max_tokens"}, "토큰 한도"), ({"refusal": True}, "거절")],
)
async def test_chat_truncation_or_refusal_stops_without_retry(
    metadata: dict[str, Any], message: str
) -> None:
    class StoppedAdapter(ChatAdapter):
        async def chat(self, request: ChatRequest, api_key: str) -> ChatResponse:
            response = await super().chat(request, api_key)
            response.provider_metadata = metadata
            return response

    adapter = StoppedAdapter()
    with pytest.raises(ExtractionError, match=message):
        await ExtractionPipeline(adapter, "key", model="chat-model").extract("본문")  # type: ignore[arg-type]
    assert len(adapter.requests) == 1


async def test_items_without_source_refs_are_dropped_with_warning() -> None:
    entity = RESPONSES["entity"]["entities"][0]
    unsourced = {
        **RESPONSES,
        "entity": {"entities": [entity, {**entity, "name": "출처 없는 사람", "source_refs": []}]},
    }

    result = await pipeline(FakeAdapter(unsourced)).extract("본문")

    assert [item.name for item in result.entities] == ["김민수"]
    assert any("source_ref 없는 항목" in warning for warning in result.warnings)

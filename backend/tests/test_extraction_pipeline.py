import json
from typing import Any

import pytest

from app.modules.context_engine.application.extraction import (
    ExtractionError,
    ExtractionPipeline,
)
from app.modules.context_engine.application.provider import (
    StructuredOutputRequest,
    StructuredOutputResponse,
)
from app.modules.context_engine.domain.ontology import EntityKind, RelationKind
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError

STAGES = ["classification", "entity", "event", "relation", "context"]

RESPONSES: dict[str, dict[str, Any]] = {
    "classification": {"source_type": "meeting", "language": "ko", "topics": ["출시 일정"]},
    "entity": {
        "entities": [
            {
                "name": "김민수",
                "kind": "Person",
                "aliases": ["민수"],
                "source_refs": ["민수가 말했다"],
            },
            {
                "name": "맥락이",
                "kind": "Project",
                "aliases": [],
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
                "source_refs": ["민수가 맥락이를 맡는다"],
            },
            {
                "source": "김민수",
                "target": "없는 개체",
                "kind": "CREATED",
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


def test_provider_without_structured_output_is_rejected() -> None:
    adapter = FakeAdapter()
    adapter.capabilities = ("chat",)

    with pytest.raises(ExtractionError):
        pipeline(adapter)


async def test_items_without_source_refs_are_dropped_with_warning() -> None:
    entity = RESPONSES["entity"]["entities"][0]
    unsourced = {
        **RESPONSES,
        "entity": {"entities": [entity, {**entity, "name": "출처 없는 사람", "source_refs": []}]},
    }

    result = await pipeline(FakeAdapter(unsourced)).extract("본문")

    assert [item.name for item in result.entities] == ["김민수"]
    assert any("source_ref 없는 항목" in warning for warning in result.warnings)

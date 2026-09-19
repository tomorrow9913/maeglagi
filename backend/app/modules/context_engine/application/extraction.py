import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.modules.context_engine.application import extraction_prompts as prompts
from app.modules.context_engine.application.provider import (
    ChatMessage,
    ProviderAdapter,
    StructuredOutputRequest,
)
from app.modules.context_engine.domain.extraction import (
    ClassificationOutput,
    ContextOutput,
    EntityOutput,
    EventOutput,
    ExtractionResult,
    RelationOutput,
)
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError

Output = TypeVar("Output", bound=BaseModel)


class ExtractionError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage} 단계 실패: {message}")
        self.stage = stage


def _with_refs(items: list[Any], stage: str, label: Any, warnings: list[str]) -> list[Any]:
    """Contract: every extracted item carries at least one non-empty source_ref."""
    kept = []
    for item in items:
        if any(ref.strip() for ref in item.source_refs):
            kept.append(item)
        else:
            warnings.append(f"{stage}: source_ref 없는 항목을 버렸습니다: {label(item)}")
    return kept


class ExtractionPipeline:
    """Classification -> Entity -> Event -> Relation -> Context.

    Every stage is its own structured-output call with its own prompt and schema.
    Later stages receive the validated output of earlier ones, never the raw model text.
    """

    def __init__(
        self,
        adapter: ProviderAdapter,
        api_key: str,
        *,
        model: str,
        temperature: float = 0.0,
    ) -> None:
        if "structuredOutput" not in adapter.capabilities:
            raise ExtractionError(
                "setup", f"{adapter.display_name}은 structuredOutput을 지원하지 않습니다."
            )
        self.adapter = adapter
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.usage: dict[str, int] = {}

    async def run_stage(
        self, stage: str, system: str, payload: dict[str, object], output_type: type[Output]
    ) -> Output:
        request = StructuredOutputRequest(
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            model=self.model,
            schema_name=f"extraction_{stage}",
            json_schema=output_type.model_json_schema(),
            temperature=self.temperature,
        )
        try:
            response = await self.adapter.structured_output(request, self.api_key)
            parsed = output_type.model_validate(response.data)
        except ProviderError as exc:
            raise ExtractionError(stage, str(exc)) from exc
        except ValidationError as exc:
            raise ExtractionError(
                stage, f"출력이 스키마와 맞지 않습니다: {exc.error_count()}건"
            ) from exc
        for key, value in response.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        return parsed

    async def extract(
        self,
        text: str,
        *,
        title: str | None = None,
        known_decisions: list[str] | None = None,
    ) -> ExtractionResult:
        self.usage = {}
        warnings: list[str] = []
        source = {"title": title, "text": text}

        classification = await self.run_stage(
            "classification", prompts.CLASSIFICATION_PROMPT, source, ClassificationOutput
        )
        classified = classification.model_dump(mode="json")

        entities = await self.run_stage(
            "entity",
            prompts.ENTITY_PROMPT,
            {**source, "classification": classified},
            EntityOutput,
        )
        entity_items = _with_refs(entities.entities, "entity", lambda i: i.name, warnings)
        entity_dump = [item.model_dump(mode="json") for item in entity_items]

        events = await self.run_stage(
            "event",
            prompts.EVENT_PROMPT,
            {
                **source,
                "classification": classified,
                "entities": entity_dump,
                "known_decisions": known_decisions or [],
            },
            EventOutput,
        )
        event_items = _with_refs(events.events, "event", lambda i: i.name, warnings)
        event_dump = [item.model_dump(mode="json") for item in event_items]

        relations = await self.run_stage(
            "relation",
            prompts.RELATION_PROMPT,
            {**source, "entities": entity_dump, "events": event_dump},
            RelationOutput,
        )
        known = {item.name for item in entity_items} | {item.name for item in event_items}
        valid_relations = []
        relation_items = _with_refs(
            relations.relations, "relation", lambda i: f"{i.source}->{i.target}", warnings
        )
        for relation in relation_items:
            if relation.source in known and relation.target in known:
                valid_relations.append(relation)
            else:
                warnings.append(
                    f"알 수 없는 개체를 가리키는 관계를 버렸습니다: "
                    f"{relation.source} -{relation.kind.value}-> {relation.target}"
                )

        contexts = await self.run_stage(
            "context",
            prompts.CONTEXT_PROMPT,
            {
                **source,
                "classification": classified,
                "entities": entity_dump,
                "events": event_dump,
                "relations": [item.model_dump(mode="json") for item in valid_relations],
            },
            ContextOutput,
        )

        context_items = _with_refs(contexts.contexts, "context", lambda i: i.title, warnings)

        return ExtractionResult(
            classification=classification,
            entities=entity_items,
            events=event_items,
            relations=valid_relations,
            contexts=context_items,
            warnings=warnings,
            usage=self.usage,
        )

"""Which models a key can use for which job.

The server never picks a model by itself: it asks the provider what the key can use, sorts the
answer into jobs (roles), and the user chooses. Whether a workspace can, say, embed is therefore a
fact about the models its key offers, not about the provider's name.
"""

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel

from app.modules.context_engine.application.provider import ModelInfo, ProviderAdapter


class ModelRole(StrEnum):
    ANSWER = "answer"
    EXTRACTION = "extraction"
    EMBEDDING = "embedding"
    TRANSCRIPTION = "transcription"


ROLE_ORDER = (
    ModelRole.ANSWER,
    ModelRole.EXTRACTION,
    ModelRole.EMBEDDING,
    ModelRole.TRANSCRIPTION,
)

# What the provider's API must be able to do for a model to serve the role at all.
ROLE_CAPABILITY = {
    ModelRole.ANSWER: "chat",
    ModelRole.EXTRACTION: "structuredOutput",
    ModelRole.EMBEDDING: "embedding",
    ModelRole.TRANSCRIPTION: "transcription",
}

# Model ids that are not chat models even though a provider lists them.
_NOT_CHAT = re.compile(
    r"embed|whisper|transcribe|tts|dall-e|image|moderation|realtime|audio|babbage|davinci|search"
)
_DATED = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8}|\d{4})$")
# Lighter (cheaper, faster) models come first: the choice is the user's, but what is preselected
# should not be the most expensive model of a family.
_LIGHT = re.compile(r"mini|nano|small|haiku|flash|lite")


class ModelOption(BaseModel):
    provider: str
    model: str


def roles_for_model(model_id: str, capabilities: tuple[str, ...]) -> set[ModelRole]:
    """The jobs `model_id` can do, judged by its id and by what the provider's API supports."""
    name = model_id.lower()
    roles: set[ModelRole] = set()
    if "embed" in name:
        roles.add(ModelRole.EMBEDDING)
    elif "whisper" in name or "transcribe" in name:
        roles.add(ModelRole.TRANSCRIPTION)
    elif not _NOT_CHAT.search(name):
        roles |= {ModelRole.ANSWER, ModelRole.EXTRACTION}
    return {role for role in roles if ROLE_CAPABILITY[role] in capabilities}


def recommendation_rank(model_id: str) -> tuple[bool, bool, str]:
    """Order of preselection: lighter models first, a stable alias before a dated snapshot.

    This is only a stable, explainable ordering. It says nothing about quality; the user picks.
    """
    return (not _LIGHT.search(model_id.lower()), bool(_DATED.search(model_id)), model_id)


def options_by_role(
    listings: list[tuple[ProviderAdapter, list[ModelInfo]]],
    prices: dict[tuple[str, str], float] | None = None,
    *,
    defaults: dict[str, dict[str, str]] | None = None,
    today: date | None = None,
) -> dict[ModelRole, list[ModelOption]]:
    """Exclude retired models, put offered defaults first, then sort other models by price."""
    today = today or date.today()
    options: dict[ModelRole, list[ModelOption]] = {role: [] for role in ROLE_ORDER}
    for adapter, infos in listings:
        live = {i.id for i in infos if i.shutdown_date is None or i.shutdown_date > today}
        preferred = (defaults or {}).get(adapter.id, {})
        for model in sorted(live, key=recommendation_rank):
            for role in ROLE_ORDER:
                if role in roles_for_model(model, adapter.capabilities):
                    option = ModelOption(provider=adapter.id, model=model)
                    if option in options[role]:
                        continue
                    if preferred.get(role.value) == model:
                        # The default leads its provider's models, after earlier keys' models.
                        first_of_provider = next(
                            (i for i, o in enumerate(options[role]) if o.provider == adapter.id),
                            len(options[role]),
                        )
                        options[role].insert(first_of_provider, option)
                    else:
                        options[role].append(option)
    if prices:
        for role in ROLE_ORDER:
            options[role].sort(
                key=lambda option: (
                    (defaults or {}).get(option.provider, {}).get(role.value) != option.model,
                    (option.provider, option.model) not in prices,
                    prices.get((option.provider, option.model), float("inf")),
                    recommendation_rank(option.model),
                    option.provider,
                )
            )
    return options


def selection_of(model_settings: dict[str, object] | None, role: ModelRole) -> ModelOption | None:
    """The workspace's stored choice for `role`, or None if it never chose."""
    raw = (model_settings or {}).get(role.value)
    if not isinstance(raw, dict):
        return None
    try:
        return ModelOption.model_validate(raw)
    except ValueError:
        return None


def invalid_selections(
    selections: dict[str, ModelOption], options: dict[ModelRole, list[ModelOption]]
) -> list[str]:
    """Why a set of choices is not acceptable: unknown role, or a model the key does not offer."""
    problems: list[str] = []
    for name, choice in selections.items():
        try:
            role = ModelRole(name)
        except ValueError:
            problems.append(f"알 수 없는 용도입니다: {name}")
            continue
        if choice not in options[role]:
            problems.append(
                f"{choice.provider}/{choice.model}은(는) {name} 용도로 쓸 수 없는 모델입니다."
            )
    return problems

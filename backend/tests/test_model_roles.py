from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.modules.context_engine.application.model_roles import (
    ModelOption,
    ModelRole,
    invalid_selections,
    options_by_role,
    recommendation_rank,
    roles_for_model,
    selection_of,
)
from app.modules.context_engine.application.provider import ModelInfo
from app.modules.context_engine.infrastructure.provider_adapters import (
    parse_anthropic_model,
    parse_openai_model,
)
from app.modules.ingestion.application import pipeline as pipeline_module
from app.modules.ingestion.application.pipeline import (
    IngestionError,
    IngestionPipeline,
    embedding_dimensions_argument,
)
from app.modules.workspaces.infrastructure.models import ProviderCredential, Workspace

OPENAI_CAPS = ("chat", "embedding", "structuredOutput", "transcription", "models")
CHAT_ONLY = ("chat", "models")


def infos(*ids: str) -> list[ModelInfo]:
    return [ModelInfo(id=model) for model in ids]


class Adapter:
    def __init__(self, provider_id: str, capabilities: tuple[str, ...]) -> None:
        self.id = provider_id
        self.display_name = provider_id
        self.capabilities = capabilities


OPENAI = Adapter("openai", OPENAI_CAPS)
ANTHROPIC = Adapter("anthropic", CHAT_ONLY)


def roles(model: str, caps: tuple[str, ...] = OPENAI_CAPS) -> set[str]:
    return {role.value for role in roles_for_model(model, caps)}


# --- sorting what a key offers into jobs ------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", {"answer", "extraction"}),
        ("text-embedding-3-small", {"embedding"}),
        ("text-embedding-ada-002", {"embedding"}),
        ("whisper-1", {"transcription"}),
        ("gpt-4o-transcribe", {"transcription"}),
        ("dall-e-3", set()),
        ("tts-1", set()),
        ("omni-moderation-latest", set()),
        ("gpt-4o-realtime-preview", set()),
        ("gpt-4o-audio-preview", set()),
    ],
)
def test_models_are_sorted_into_the_jobs_they_can_do(model: str, expected: set[str]) -> None:
    assert roles(model) == expected


def test_a_chat_model_extracts_only_where_the_provider_supports_structured_output() -> None:
    assert roles("claude-sonnet", CHAT_ONLY) == {"answer"}


def test_a_job_the_providers_api_cannot_do_has_no_models_whatever_they_are_called() -> None:
    assert roles("text-embedding-3-small", CHAT_ONLY) == set()
    assert roles("whisper-1", CHAT_ONLY) == set()


def test_lighter_models_are_preselected_before_heavier_ones_of_the_same_family() -> None:
    assert sorted(["gpt-4o", "gpt-4o-mini"], key=recommendation_rank)[0] == "gpt-4o-mini"
    embeddings = ["text-embedding-3-large", "text-embedding-3-small"]
    assert sorted(embeddings, key=recommendation_rank)[0] == "text-embedding-3-small"


def test_a_stable_alias_comes_before_a_dated_snapshot_of_the_same_model() -> None:
    ranked = sorted(["gpt-4o-mini-2024-07-18", "gpt-4o-mini"], key=recommendation_rank)

    assert ranked == ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"]


def test_options_are_grouped_by_job_and_a_job_nobody_offers_stays_empty() -> None:
    options = options_by_role(
        [(OPENAI, infos("gpt-4o-mini", "text-embedding-3-small", "whisper-1", "dall-e-3"))]
    )

    assert [o.model for o in options[ModelRole.ANSWER]] == ["gpt-4o-mini"]
    assert [o.model for o in options[ModelRole.EMBEDDING]] == ["text-embedding-3-small"]
    assert [o.model for o in options[ModelRole.TRANSCRIPTION]] == ["whisper-1"]

    chat_only = options_by_role([(ANTHROPIC, infos("claude-sonnet", "claude-haiku"))])
    assert len(chat_only[ModelRole.ANSWER]) == 2
    assert chat_only[ModelRole.EMBEDDING] == [] and chat_only[ModelRole.TRANSCRIPTION] == []
    assert chat_only[ModelRole.EXTRACTION] == []


def test_two_keys_offer_a_job_in_key_priority_order_without_duplicates() -> None:
    options = options_by_role(
        [(ANTHROPIC, infos("claude-sonnet")), (OPENAI, infos("gpt-4o-mini", "gpt-4o-mini"))]
    )

    assert [(o.provider, o.model) for o in options[ModelRole.ANSWER]] == [
        ("anthropic", "claude-sonnet"),
        ("openai", "gpt-4o-mini"),
    ]


def test_a_choice_must_be_a_model_the_key_offers_for_that_job() -> None:
    options = options_by_role([(OPENAI, infos("gpt-4o-mini", "text-embedding-3-small"))])
    good = ModelOption(provider="openai", model="text-embedding-3-small")

    assert invalid_selections({"embedding": good}, options) == []
    wrong_job = invalid_selections({"answer": good}, options)
    assert len(wrong_job) == 1 and "answer" in wrong_job[0]
    assert len(invalid_selections({"nonsense": good}, options)) == 1


def test_a_stored_choice_that_is_garbage_counts_as_no_choice() -> None:
    assert selection_of({"answer": "gpt"}, ModelRole.ANSWER) is None
    assert selection_of({"answer": {"provider": "openai"}}, ModelRole.ANSWER) is None
    assert selection_of(None, ModelRole.ANSWER) is None
    assert selection_of({"answer": {"provider": "openai", "model": "m"}}, ModelRole.ANSWER) == (
        ModelOption(provider="openai", model="m")
    )


def test_only_the_text_embedding_3_family_is_asked_for_a_dimension() -> None:
    assert embedding_dimensions_argument("text-embedding-3-large", 1536) == 1536
    assert embedding_dimensions_argument("text-embedding-ada-002", 1536) is None


# --- the pipeline uses what the workspace chose ----------------------------------------------

WORKSPACE = uuid4()
OWNER = uuid4()


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class Session:
    def __init__(self, model_settings: dict[str, Any], providers: list[str]) -> None:
        self.workspace = Workspace(
            id=WORKSPACE, owner_id=OWNER, name="w", model_settings=model_settings
        )
        self.credentials = [
            ProviderCredential(
                workspace_id=WORKSPACE,
                owner_id=OWNER,
                provider=p,
                key_hint="1234",
                is_default=i == 0,
            )
            for i, p in enumerate(providers)
        ]

    async def get(self, model: Any, identifier: Any) -> Workspace:
        return self.workspace

    async def exec(self, statement: Any) -> Result:
        return Result(self.credentials)


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> None:
    adapters = {"openai": OPENAI, "anthropic": ANTHROPIC}

    async def secret(session: Any, credential: Any) -> str:
        return f"key-of-{credential.provider}"

    monkeypatch.setattr(pipeline_module.provider_registry, "get", adapters.get)
    monkeypatch.setattr(pipeline_module, "resolve_credential_secret", secret)


def pipeline() -> IngestionPipeline:
    return IngestionPipeline(Settings(_env_file=None, embedding_model="deployment-default"))


async def resolve(settings: dict[str, Any], keys: list[str], role: ModelRole) -> Any:
    return await pipeline().provider_with_model(
        Session(settings, keys),  # type: ignore[arg-type]
        workspace_id=WORKSPACE,
        owner_id=OWNER,
        role=role,
    )


async def test_the_workspaces_choice_decides_the_model(providers: None) -> None:
    chosen = {"embedding": {"provider": "openai", "model": "text-embedding-3-large"}}

    resolved = await resolve(chosen, ["openai"], ModelRole.EMBEDDING)

    assert (resolved.adapter.id, resolved.model, resolved.api_key) == (
        "openai",
        "text-embedding-3-large",
        "key-of-openai",
    )


async def test_a_workspace_that_never_chose_gets_that_providers_default(providers: None) -> None:
    resolved = await resolve({}, ["openai"], ModelRole.EMBEDDING)

    assert resolved.model == "text-embedding-3-small"  # the provider's default, not a guess


async def test_the_key_of_the_chosen_models_provider_is_used_even_if_it_is_not_the_default(
    providers: None,
) -> None:
    chosen = {"answer": {"provider": "openai", "model": "gpt-4o"}}

    resolved = await resolve(chosen, ["anthropic", "openai"], ModelRole.ANSWER)

    assert (resolved.adapter.id, resolved.model) == ("openai", "gpt-4o")


async def test_a_job_the_only_key_cannot_do_is_an_error_not_a_guess(providers: None) -> None:
    with pytest.raises(IngestionError, match="embedding"):
        await resolve({}, ["anthropic"], ModelRole.EMBEDDING)


async def test_a_choice_whose_key_is_gone_falls_back_instead_of_calling_the_wrong_provider(
    providers: None,
) -> None:
    chosen = {"answer": {"provider": "openai", "model": "gpt-4o"}}

    resolved = await resolve(chosen, ["anthropic"], ModelRole.ANSWER)

    assert resolved.adapter.id == "anthropic"
    assert resolved.model != "gpt-4o"  # never sends an OpenAI model name to Anthropic


async def test_an_unchosen_job_never_sends_one_providers_model_name_to_another(
    providers: None,
) -> None:
    resolved = await resolve({}, ["anthropic"], ModelRole.ANSWER)

    assert resolved.adapter.id == "anthropic"
    assert resolved.model == "claude-haiku-4-5"  # anthropic's default, not an OpenAI name


async def test_provider_fallback_override_takes_precedence(providers: None) -> None:
    configured = Settings(
        _env_file=None,
        provider_fallback_models={"anthropic": {"answer": "claude-sonnet-custom"}},
    )
    resolved = await IngestionPipeline(configured).provider_with_model(
        Session({}, ["anthropic"]),  # type: ignore[arg-type]
        workspace_id=WORKSPACE,
        owner_id=OWNER,
        role=ModelRole.ANSWER,
    )

    assert resolved.model == "claude-sonnet-custom"


# --- what the provider reports: retirement, defaults, release dates --------------------------

TODAY = date(2026, 9, 20)


def test_a_model_the_provider_has_already_retired_is_not_offered() -> None:
    options = options_by_role(
        [
            (
                OPENAI,
                [
                    ModelInfo(id="gpt-old", shutdown_date=date(2026, 9, 1)),
                    ModelInfo(id="gpt-today", shutdown_date=TODAY),
                    ModelInfo(id="gpt-later", shutdown_date=date(2026, 12, 1)),
                    ModelInfo(id="gpt-4o-mini"),
                ],
            )
        ],
        today=TODAY,
    )

    assert {o.model for o in options[ModelRole.ANSWER]} == {"gpt-later", "gpt-4o-mini"}


def test_the_providers_default_leads_its_models_when_the_key_offers_it() -> None:
    options = options_by_role(
        [(OPENAI, infos("gpt-4.1", "gpt-4o-mini", "gpt-4o"))],
        defaults={"openai": {"answer": "gpt-4.1"}},
    )

    assert options[ModelRole.ANSWER][0].model == "gpt-4.1"


def test_a_default_the_key_does_not_offer_is_skipped_instead_of_invented() -> None:
    options = options_by_role(
        [(OPENAI, infos("gpt-4o-mini", "gpt-4o"))],
        defaults={"openai": {"answer": "model-this-key-lacks"}},
    )

    assert "model-this-key-lacks" not in {o.model for o in options[ModelRole.ANSWER]}
    assert options[ModelRole.ANSWER][0].model == "gpt-4o-mini"


def test_a_default_that_was_retired_is_not_preselected() -> None:
    options = options_by_role(
        [(OPENAI, [ModelInfo(id="gpt-4.1", shutdown_date=date(2026, 1, 1)), *infos("gpt-4o")])],
        defaults={"openai": {"answer": "gpt-4.1"}},
        today=TODAY,
    )

    assert [o.model for o in options[ModelRole.ANSWER]] == ["gpt-4o"]


def test_each_providers_default_only_leads_that_providers_models() -> None:
    options = options_by_role(
        [
            (ANTHROPIC, infos("claude-sonnet", "claude-haiku")),
            (OPENAI, infos("gpt-4o", "gpt-4o-mini")),
        ],
        defaults={"openai": {"answer": "gpt-4o"}, "anthropic": {"answer": "claude-sonnet"}},
    )

    assert [(o.provider, o.model) for o in options[ModelRole.ANSWER]] == [
        ("anthropic", "claude-sonnet"),
        ("anthropic", "claude-haiku"),
        ("openai", "gpt-4o"),
        ("openai", "gpt-4o-mini"),
    ]


def test_openai_style_metadata_is_read_from_the_models_list() -> None:
    info = parse_openai_model(
        {"id": "gpt-x", "created": 1686935002, "shutdown_date": "2027-02-03", "owned_by": "o"}
    )

    assert info is not None
    assert info.id == "gpt-x"
    assert info.created == datetime(2023, 6, 16, 17, 3, 22, tzinfo=UTC)
    assert info.shutdown_date == date(2027, 2, 3)


def test_missing_or_odd_metadata_is_unknown_not_an_error() -> None:
    bare = parse_openai_model({"id": "gpt-x"})
    odd = parse_openai_model({"id": "gpt-y", "created": "soon", "shutdown_date": 5})

    assert bare == ModelInfo(id="gpt-x")
    assert odd == ModelInfo(id="gpt-y")
    assert parse_openai_model({"object": "model"}) is None
    assert parse_openai_model("nope") is None


def test_anthropic_metadata_is_read_from_the_models_list() -> None:
    info = parse_anthropic_model({"id": "claude-x", "created_at": "2026-07-24T00:00:00Z"})

    assert info is not None
    assert info.created == datetime(2026, 7, 24, tzinfo=UTC)
    assert info.shutdown_date is None
    assert parse_anthropic_model({"id": "claude-y", "created_at": "garbage"}) == ModelInfo(
        id="claude-y"
    )

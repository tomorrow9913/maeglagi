import importlib
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.ai import models as models_module
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.application.model_catalog import with_recommended_defaults
from app.modules.context_engine.application.model_roles import (
    ModelOption,
    ModelRole,
    options_by_role,
)
from app.modules.context_engine.application.provider import ModelInfo
from app.modules.workspaces.infrastructure.models import Workspace

# `app.api.workspaces.router` is shadowed by the package's `router` attribute, so load the module.
workspaces_router_module = importlib.import_module("app.api.workspaces.router")

USER = uuid4()
WORKSPACE = uuid4()


class Adapter:
    def __init__(self, provider_id: str, capabilities: tuple[str, ...]) -> None:
        self.id, self.display_name, self.capabilities = provider_id, provider_id, capabilities


OPENAI = Adapter("openai", ("chat", "embedding", "structuredOutput", "transcription", "models"))
OPTIONS = options_by_role(
    [
        (
            OPENAI,
            [
                ModelInfo(id=model)
                for model in (
                    "gpt-4o-mini",
                    "gpt-4o",
                    "text-embedding-3-small",
                    "text-embedding-3-large",
                    "whisper-1",
                )
            ],
        )
    ]
)
EMBED_SMALL = {"provider": "openai", "model": "text-embedding-3-small"}
EMBED_LARGE = {"provider": "openai", "model": "text-embedding-3-large"}


class FakeSession:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, model: Any, identifier: Any) -> Workspace | None:
        return self.workspace if identifier == self.workspace.id else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        pass


class Env:
    def __init__(self) -> None:
        self.workspace = Workspace(id=WORKSPACE, owner_id=USER, name="맥락이", model_settings={})
        self.session = FakeSession(self.workspace)
        self.indexed = False


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    state = Env()

    async def options_for_workspace(
        session: Any, workspace: Any, owner: Any, provider: str | None = None
    ) -> Any:
        return {
            role: [option for option in items if provider is None or option.provider == provider]
            for role, items in OPTIONS.items()
        }

    async def has_chunks(*_: Any) -> bool:
        return state.indexed

    async def validate(provider: str, api_key: str) -> tuple[bool, str]:
        return (api_key == "good-key", "ok" if api_key == "good-key" else "유효하지 않은 키입니다.")

    async def options_for_key(provider: str, api_key: str) -> Any:
        return OPTIONS

    monkeypatch.setattr(models_module, "options_for_workspace", options_for_workspace)
    monkeypatch.setattr(models_module, "has_indexed_chunks", has_chunks)
    monkeypatch.setattr(models_module, "validate_provider_credential", validate)
    monkeypatch.setattr(models_module, "options_for_key", options_for_key)
    monkeypatch.setattr(workspaces_router_module, "validate_provider_credential", validate)
    monkeypatch.setattr(workspaces_router_module, "options_for_key", options_for_key)

    async def store_secret(*_: Any, **__: Any) -> UUID:
        return uuid4()

    monkeypatch.setattr(workspaces_router_module, "store_credential_secret", store_secret)

    async def session() -> Any:
        yield state.session

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, embedding_model="text-embedding-3-small"
    )
    try:
        yield state
    finally:
        app.dependency_overrides.clear()


def get_models(client: TestClient) -> Any:
    return client.get(f"/api/v1/workspaces/{WORKSPACE}/ai/models")


def put_models(client: TestClient, selections: dict[str, Any]) -> Any:
    return client.put(f"/api/v1/workspaces/{WORKSPACE}/ai/models", json={"selections": selections})


def by_role(response: Any) -> dict[str, Any]:
    return {item["role"]: item for item in response.json()["roles"]}


# --- a key on its own -------------------------------------------------------------------------


def test_a_valid_key_lists_its_models_by_job_in_a_fixed_order(env: Env) -> None:
    response = TestClient(app).post(
        "/api/v1/llm-keys/models", json={"provider": "openai", "apiKey": "good-key"}
    )

    assert response.status_code == 200
    assert [r["role"] for r in response.json()["roles"]] == [
        "answer",
        "extraction",
        "embedding",
        "transcription",
    ]
    embedding = by_role(response)["embedding"]
    assert [o["model"] for o in embedding["options"]] == [
        "text-embedding-3-small",
        "text-embedding-3-large",
    ]
    assert (embedding["selected"], embedding["locked"]) == (None, False)


def test_an_invalid_key_is_a_422_with_the_reason(env: Env) -> None:
    response = TestClient(app).post(
        "/api/v1/llm-keys/models", json={"provider": "openai", "apiKey": "bad"}
    )

    assert response.status_code == 422
    assert "유효하지 않은 키" in response.json()["detail"]


# --- a workspace's models ---------------------------------------------------------------------


def test_the_workspace_shows_what_it_chose_and_leaves_the_rest_unset(env: Env) -> None:
    env.workspace.model_settings = {"answer": {"provider": "openai", "model": "gpt-4o"}}

    roles = by_role(get_models(TestClient(app)))

    assert roles["answer"]["selected"] == {"provider": "openai", "model": "gpt-4o"}
    assert roles["embedding"]["selected"] is None


def test_a_stored_choice_the_key_no_longer_offers_remains_visible(env: Env) -> None:
    env.workspace.model_settings = {"answer": {"provider": "openai", "model": "retired-model"}}

    assert by_role(get_models(TestClient(app)))["answer"]["selected"] == {
        "provider": "openai",
        "model": "retired-model",
    }


def test_provider_browsing_filters_options_without_changing_saved_models(env: Env) -> None:
    env.workspace.model_settings = {"embedding": EMBED_SMALL}
    response = TestClient(app).get(
        f"/api/v1/workspaces/{WORKSPACE}/ai/models", params={"provider": "anthropic"}
    )
    assert response.status_code == 200
    roles = by_role(response)
    assert all(not role["options"] for role in roles.values())
    assert roles["embedding"]["selected"] == EMBED_SMALL
    assert roles["embedding"]["locked"] is True
    assert env.workspace.model_settings == {"embedding": EMBED_SMALL}
    assert env.session.commits == 0


def test_provider_filter_preserves_matching_options_and_rejects_unknown_provider(env: Env) -> None:
    client = TestClient(app)
    path = f"/api/v1/workspaces/{WORKSPACE}/ai/models"
    response = client.get(path, params={"provider": "openai"})
    assert response.status_code == 200
    assert by_role(response)["answer"]["options"]
    assert client.get(path, params={"provider": "unknown"}).status_code == 422
    env.workspace.owner_id = uuid4()
    assert client.get(path, params={"provider": "openai"}).status_code == 404


def test_the_embedding_model_is_locked_once_sources_are_indexed(env: Env) -> None:
    env.indexed = True

    roles = by_role(get_models(TestClient(app)))

    assert roles["embedding"]["locked"] is True
    assert roles["answer"]["locked"] is False


def test_choosing_models_saves_them_on_the_workspace(env: Env) -> None:
    response = put_models(
        TestClient(app),
        {"answer": {"provider": "openai", "model": "gpt-4o"}, "embedding": EMBED_LARGE},
    )

    assert response.status_code == 200
    assert env.workspace.model_settings["answer"]["model"] == "gpt-4o"
    assert env.workspace.model_settings["embedding"] == EMBED_LARGE
    assert env.session.commits == 1
    assert by_role(response)["answer"]["selected"]["model"] == "gpt-4o"


def test_a_partial_update_keeps_the_choices_it_does_not_mention(env: Env) -> None:
    env.workspace.model_settings = {"transcription": {"provider": "openai", "model": "whisper-1"}}

    put_models(TestClient(app), {"answer": {"provider": "openai", "model": "gpt-4o"}})

    assert env.workspace.model_settings["transcription"]["model"] == "whisper-1"


def test_models_can_mix_providers_independently_by_role(env: Env, monkeypatch) -> None:
    claude = ModelOption(provider="anthropic", model="claude-test")

    async def mixed_options(*args):
        return {**OPTIONS, ModelRole.ANSWER: [*OPTIONS[ModelRole.ANSWER], claude]}

    monkeypatch.setattr(models_module, "options_for_workspace", mixed_options)
    selections = {
        "answer": claude.model_dump(),
        "embedding": EMBED_SMALL,
        "transcription": {"provider": "openai", "model": "whisper-1"},
    }
    response = put_models(TestClient(app), selections)
    assert response.status_code == 200
    assert env.workspace.model_settings == selections
    assert {o["provider"] for o in by_role(response)["answer"]["options"]} == {
        "openai",
        "anthropic",
    }


def test_a_model_the_key_does_not_offer_for_that_job_is_a_422(env: Env) -> None:
    response = put_models(TestClient(app), {"answer": EMBED_SMALL})

    assert response.status_code == 422
    assert env.workspace.model_settings == {}


def test_an_unknown_job_is_a_422(env: Env) -> None:
    assert put_models(TestClient(app), {"summary": EMBED_SMALL}).status_code == 422


def test_changing_the_embedding_model_after_indexing_is_a_409(env: Env) -> None:
    env.indexed = True
    env.workspace.model_settings = {"embedding": EMBED_SMALL}

    response = put_models(TestClient(app), {"embedding": EMBED_LARGE})

    assert response.status_code == 409
    assert "워크스페이스를 만들 때 정해지며" in response.json()["detail"]
    assert env.workspace.model_settings["embedding"] == EMBED_SMALL


def test_resending_the_same_embedding_model_after_indexing_is_fine(env: Env) -> None:
    env.indexed = True
    env.workspace.model_settings = {"embedding": EMBED_SMALL}

    assert put_models(TestClient(app), {"embedding": EMBED_SMALL}).status_code == 200


def test_a_locked_workspace_that_never_chose_may_record_the_legacy_provider_and_model_only(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env.indexed = True  # embedded earlier with the deployment default: text-embedding-3-small

    async def legacy_provider(*args: Any, **kwargs: Any) -> Any:
        from app.modules.ingestion.application.pipeline import ResolvedProvider

        return ResolvedProvider(OPENAI, "old-key", "text-embedding-3-small")

    monkeypatch.setattr(models_module.IngestionPipeline, "provider_with_model", legacy_provider)

    async def options_with_other_provider(*args: Any) -> Any:
        return {
            **OPTIONS,
            ModelRole.EMBEDDING: [
                *OPTIONS[ModelRole.EMBEDDING],
                ModelOption(provider="other", model="text-embedding-3-small"),
            ],
        }

    monkeypatch.setattr(models_module, "options_for_workspace", options_with_other_provider)

    assert put_models(TestClient(app), {"embedding": EMBED_LARGE}).status_code == 409
    wrong_provider = {"embedding": {**EMBED_SMALL, "provider": "other"}}
    assert put_models(TestClient(app), wrong_provider).status_code == 409
    assert put_models(TestClient(app), {"embedding": EMBED_SMALL}).status_code == 200


def test_other_jobs_stay_changeable_after_indexing(env: Env) -> None:
    env.indexed = True

    response = put_models(TestClient(app), {"answer": {"provider": "openai", "model": "gpt-4o"}})

    assert response.status_code == 200


def test_someone_elses_workspace_is_a_404(env: Env) -> None:
    env.workspace.owner_id = uuid4()

    assert get_models(TestClient(app)).status_code == 404
    assert put_models(TestClient(app), {}).status_code == 404


# --- creating a workspace ---------------------------------------------------------------------


def create(models: dict[str, Any] | None = None, key: str = "good-key") -> Any:
    body: dict[str, Any] = {"name": "새 워크스페이스", "llmProvider": "openai", "llmApiKey": key}
    if models is not None:
        body["models"] = models
    return TestClient(app).post("/api/v1/workspaces", json=body)


def created_workspace(env: Env) -> Workspace:
    return next(item for item in env.session.added if isinstance(item, Workspace))


def test_the_chosen_models_are_stored_and_the_rest_get_the_recommended_one(env: Env) -> None:
    response = create({"embedding": EMBED_LARGE})

    assert response.status_code == 201
    settings = created_workspace(env).model_settings
    assert settings["embedding"] == EMBED_LARGE  # what the user chose wins
    assert settings["answer"]["model"] == "gpt-4o-mini"  # recommended alias, not the dated one
    assert settings["transcription"]["model"] == "whisper-1"


def test_creating_without_choices_stores_the_recommendation_for_every_offered_job(
    env: Env,
) -> None:
    create()

    assert set(created_workspace(env).model_settings) == {
        "answer",
        "extraction",
        "embedding",
        "transcription",
    }


def test_a_workspace_is_not_created_with_a_model_the_key_does_not_offer(env: Env) -> None:
    response = create({"answer": EMBED_SMALL})

    assert response.status_code == 422
    assert not any(isinstance(item, Workspace) for item in env.session.added)


def test_a_workspace_is_not_created_with_an_invalid_key(env: Env) -> None:
    assert create(key="bad").status_code == 422


def test_missing_jobs_are_filled_without_touching_choices() -> None:
    chosen = {"answer": {"provider": "anthropic", "model": "claude-sonnet"}}

    merged = with_recommended_defaults(chosen, OPTIONS)

    assert merged["answer"] == chosen["answer"]
    assert merged["embedding"] == ModelOption(**EMBED_SMALL).model_dump()
    assert ModelRole.TRANSCRIPTION.value in merged


def test_the_paths_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/llm-keys/models" in paths
    assert {"get", "put"} <= set(paths["/api/v1/workspaces/{workspace_id}/ai/models"])


# --- the embedding model is fixed when the workspace is created; LLM models change freely -----


def test_the_embedding_model_is_locked_as_soon_as_it_is_chosen_even_before_any_indexing(
    env: Env,
) -> None:
    env.workspace.model_settings = {"embedding": EMBED_SMALL}  # chosen at creation, nothing indexed

    roles = by_role(get_models(TestClient(app)))

    assert env.indexed is False
    assert roles["embedding"]["locked"] is True


def test_a_workspace_that_never_chose_can_choose_the_embedding_model_exactly_once(
    env: Env,
) -> None:
    assert by_role(get_models(TestClient(app)))["embedding"]["locked"] is False

    assert put_models(TestClient(app), {"embedding": EMBED_LARGE}).status_code == 200

    assert by_role(get_models(TestClient(app)))["embedding"]["locked"] is True
    assert put_models(TestClient(app), {"embedding": EMBED_SMALL}).status_code == 409
    assert env.workspace.model_settings["embedding"] == EMBED_LARGE


def test_changing_the_embedding_model_is_refused_even_though_nothing_is_indexed(env: Env) -> None:
    env.workspace.model_settings = {"embedding": EMBED_SMALL}

    response = put_models(TestClient(app), {"embedding": EMBED_LARGE})

    assert response.status_code == 409
    assert env.workspace.model_settings["embedding"] == EMBED_SMALL


@pytest.mark.parametrize("role", ["answer", "extraction", "transcription"])
def test_every_llm_job_can_be_changed_freely_even_with_the_embedding_locked(
    env: Env, role: str
) -> None:
    env.indexed = True
    env.workspace.model_settings = {"embedding": EMBED_SMALL}
    first, second = OPTIONS[ModelRole(role)][0], OPTIONS[ModelRole(role)][-1]

    for choice in (second, first, second):  # back and forth, as often as the user likes
        response = put_models(TestClient(app), {role: choice.model_dump()})
        assert response.status_code == 200
        assert env.workspace.model_settings[role] == choice.model_dump()

    assert env.workspace.model_settings["embedding"] == EMBED_SMALL  # untouched throughout


def test_a_workspace_created_with_an_embedding_model_starts_locked(env: Env) -> None:
    create({"embedding": EMBED_LARGE})
    made = created_workspace(env)
    made.id = WORKSPACE  # the fake session serves exactly one workspace id
    env.session.workspace = made

    roles = by_role(get_models(TestClient(app)))

    assert roles["embedding"]["selected"] == EMBED_LARGE
    assert roles["embedding"]["locked"] is True

"""Directory identity and explicit graph projection stay independent of model output."""

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import SecretStr

from app.api.workspaces import source_content
from app.api.workspaces.credentials import _credential_key
from app.api.workspaces.directory import PersonInput, create_person, normalize_email
from app.api.workspaces.graph import get_knowledge_graph
from app.api.workspaces.review import _snapshot
from app.api.workspaces.schemas import CreateWorkspaceRequest, CredentialInput
from app.auth.models import AuthUser
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

OWNER, WORKSPACE = uuid4(), uuid4()


class Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values

    def first(self) -> Any:
        return self.values[0] if self.values else None


class Session:
    def __init__(self) -> None:
        self.workspace = Workspace(id=WORKSPACE, owner_id=OWNER, name="Test")
        self.person = WorkspacePerson(
            workspace_id=WORKSPACE,
            owner_id=OWNER,
            name="Kim",
            email="Kim@example.com",
            email_normalized="kim@example.com",
        )
        self.project = WorkspaceProject(workspace_id=WORKSPACE, owner_id=OWNER, name="Project")
        self.source = Source(
            workspace_id=WORKSPACE,
            owner_id=OWNER,
            kind="meeting",
            title="Meeting",
            object_path="path",
            content_type="audio/wav",
            size_bytes=10,
            review_state="confirmed",
            status="processing",
        )
        self.rows = {
            WorkspacePerson: [self.person],
            WorkspaceProject: [self.project],
            ProjectMember: [
                ProjectMember(
                    workspace_id=WORKSPACE,
                    project_id=self.project.id,
                    person_id=self.person.id,
                )
            ],
            Source: [self.source],
            SourceProject: [
                SourceProject(
                    workspace_id=WORKSPACE,
                    source_id=self.source.id,
                    project_id=self.project.id,
                )
            ],
            SourcePerson: [
                SourcePerson(
                    workspace_id=WORKSPACE,
                    source_id=self.source.id,
                    person_id=self.person.id,
                    role="participant",
                )
            ],
        }

    async def get(self, model: Any, identifier: UUID, **_kwargs: Any) -> Any:
        if model is Workspace and identifier == WORKSPACE:
            return self.workspace
        if model is Source and identifier == self.source.id:
            return self.source
        return None

    async def exec(self, statement: Any) -> Rows:
        entities = [item.get("entity") for item in getattr(statement, "column_descriptions", [])]
        for model, rows in self.rows.items():
            if model in entities:
                return Rows(rows)
        return Rows([])

    def add(self, item: Any) -> None:
        if isinstance(item, WorkspacePerson):
            self.rows[WorkspacePerson] = [item]

    async def commit(self) -> None:
        pass


def test_email_normalization_is_stable_and_rejects_bad_values() -> None:
    assert normalize_email("  Kim@Example.COM  ") == ("Kim@Example.COM", "kim@example.com")
    with pytest.raises(ValueError):
        normalize_email("not an email")


def test_keyless_ollama_marker_keeps_other_providers_keyed() -> None:
    assert _credential_key("ollama", None) == ""
    assert CredentialInput(provider="ollama").api_key is None
    assert CreateWorkspaceRequest(name="Local", llmProvider="ollama").llm_api_key is None
    with pytest.raises(HTTPException):
        _credential_key("openai", None)
    assert _credential_key("ollama", "optional-key") == "optional-key"


async def test_same_email_create_reuses_person_identity() -> None:
    session = Session()
    response = Response()
    person = await create_person(
        WORKSPACE,
        PersonInput(name="Different", email="KIM@example.com", aliases=["K"]),
        AuthUser(id=OWNER),
        session,
        response,  # type: ignore[arg-type]
    )
    assert response.status_code == 200
    assert person.id == session.person.id
    assert person.name == "Kim"
    assert person.aliases == ["K"]


def test_confirmation_snapshot_keeps_all_projects_without_inventing_attendance() -> None:
    session = Session()
    second = WorkspaceProject(workspace_id=WORKSPACE, owner_id=OWNER, name="Second")
    snapshot = _snapshot([session.project, second], {}, {})
    assert snapshot["project"]["id"] == str(session.project.id)
    assert [item["id"] for item in snapshot["projects"]] == [
        str(session.project.id),
        str(second.id),
    ]
    assert snapshot["people"] == []


async def test_material_graph_uses_directory_ids_and_hides_materials_on_request() -> None:
    session = Session()
    user = AuthUser(id=OWNER)
    graph = await get_knowledge_graph(
        WORKSPACE,
        user,
        session,
        None,
        include_materials=True,  # type: ignore[arg-type]
    )
    material = [node for node in graph.nodes if node.material]
    assert len(material) == 1
    assert material[0].source_id == session.source.id
    assert {edge.role for edge in graph.edges if edge.explicit} == {
        "member",
        "project",
        "participant",
    }
    hidden = await get_knowledge_graph(
        WORKSPACE,
        user,
        session,
        None,
        include_materials=False,  # type: ignore[arg-type]
    )
    assert all(not node.material for node in hidden.nodes)
    assert {edge.role for edge in hidden.edges} == {"member"}


async def test_directory_label_overrides_stale_graph_and_material_links_extraction() -> None:
    session = Session()
    stale_id, decision_id = uuid4(), uuid4()

    class GraphStore:
        async def execute(self, query: str, _params: Any = None) -> list[dict[str, Any]]:
            if "RETURN e.id AS id" not in query:
                return []
            return [
                {
                    "id": str(stale_id),
                    "kind": "Person",
                    "name": "Old name",
                    "source_ids": [],
                    "superseded_by": None,
                    "identifiers": [f"directory:person:{session.person.id}"],
                },
                {
                    "id": str(decision_id),
                    "kind": "Decision",
                    "name": "Chosen plan",
                    "source_ids": [str(session.source.id)],
                    "superseded_by": None,
                    "identifiers": [],
                },
            ]

    user = AuthUser(id=OWNER)
    graph = await get_knowledge_graph(
        WORKSPACE,
        user,
        session,
        GraphStore(),
        include_materials=True,  # type: ignore[arg-type]
    )
    directory_node = next(node for node in graph.nodes if node.id == str(stale_id))
    assert directory_node.label == "Kim"
    assert directory_node.directory_id == session.person.id
    assert directory_node.directory_kind == "Person"
    assert any(
        edge.source == str(decision_id) and edge.kind == "MENTIONED_IN" for edge in graph.edges
    )
    hidden = await get_knowledge_graph(
        WORKSPACE,
        user,
        session,
        GraphStore(),
        include_materials=False,  # type: ignore[arg-type]
    )
    assert all(edge.kind != "MENTIONED_IN" for edge in hidden.edges)
    assert all(not node.material for node in hidden.nodes)


async def test_export_uses_only_confirmed_review_text() -> None:
    session = Session()
    session.source.review_utterances = [
        {
            "id": "u1",
            "speakerName": "Kim",
            "text": "Edited words",
            "startSeconds": 61,
        }
    ]
    session.source.raw_transcript_text = "Incorrect raw words"
    result = await source_content.export_meeting_markdown(
        session.source.id,
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert result.media_type.startswith("text/markdown")
    assert "[01:01] **Kim**" in result.body.decode()
    assert "Edited words" in result.body.decode()
    assert "Incorrect raw words" not in result.body.decode()
    session.source.review_state = "awaiting_review"
    with pytest.raises(HTTPException) as exc:
        await source_content.export_meeting_markdown(
            session.source.id,
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


async def test_playback_signs_only_an_owned_audio_source(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session()

    class HttpResult:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"signedURL": "/object/sign/private/path?token=short-lived"}

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            pass

        async def post(self, url: str, *, json: Any, headers: Any) -> HttpResult:
            assert url.endswith("/object/sign/private/path")
            assert json == {"expiresIn": 300}
            assert headers["Authorization"] == "Bearer service-secret"
            return HttpResult()

    monkeypatch.setattr(
        source_content,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://storage.example",
            supabase_storage_bucket="private",
            supabase_service_role_key=SecretStr("service-secret"),
        ),
    )
    monkeypatch.setattr(source_content.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = await source_content.recording_playback_url(
        session.source.id,
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert result.url.endswith("?token=short-lived")
    assert isinstance(result.expires_at, datetime)
    session.source.content_type = "text/plain"
    with pytest.raises(HTTPException) as exc:
        await source_content.recording_playback_url(
            session.source.id,
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 404


async def test_source_content_exposes_actual_recording_capability() -> None:
    session = Session()
    user = AuthUser(id=OWNER)
    audio = await source_content.get_source_content(
        session.source.id,
        user,
        session,  # type: ignore[arg-type]
    )
    assert audio.has_recording is True
    session.source.content_type = "text/plain"
    text_only = await source_content.get_source_content(
        session.source.id,
        user,
        session,  # type: ignore[arg-type]
    )
    assert text_only.has_recording is False

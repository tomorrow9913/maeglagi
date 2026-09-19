from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError

from app.api.workspaces import review as review_module
from app.api.workspaces.associations import AssociationsPatch, patch_associations
from app.api.workspaces.directory import (
    PersonInput,
    ProjectInput,
    create_person,
    create_project,
)
from app.api.workspaces.review import (
    ConfirmRequest,
    ReviewPatch,
    confirm_review,
    retry_transcription,
    review_payload,
    save_review,
)
from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import create_app
from app.modules.workspaces.infrastructure.models import (
    Source,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

OWNER, WORKSPACE = uuid4(), uuid4()
OTHER = uuid4()


class FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def first(self) -> Source:
        return self.value

    def all(self) -> list[Any]:
        return [self.value] if self.value is not None else []


class FakeSession:
    def __init__(self) -> None:
        self.workspace = Workspace(id=WORKSPACE, owner_id=OWNER, name="Workspace")
        self.source = Source(
            workspace_id=WORKSPACE,
            owner_id=OWNER,
            kind="meeting",
            title="Meeting",
            object_path="test",
            content_type="text/plain",
            size_bytes=1,
            review_state="awaiting_review",
            status="awaiting_review",
            processing_stage="awaiting_review",
        )
        self.people: dict[UUID, WorkspacePerson] = {}
        self.projects: dict[UUID, WorkspaceProject] = {}
        self.commits = 0

    async def get(self, model: Any, identifier: UUID, **kwargs: Any) -> Any:
        if model is Workspace:
            return self.workspace if identifier == self.workspace.id else None
        if model is Source:
            return self.source if identifier == self.source.id else None
        if model is WorkspacePerson:
            return self.people.get(identifier)
        if model is WorkspaceProject:
            return self.projects.get(identifier)
        return None

    async def exec(self, statement: Any) -> FakeResult:
        entities = [item.get("entity") for item in getattr(statement, "column_descriptions", [])]
        return FakeResult(self.source if Source in entities else None)

    def add(self, item: Any) -> None:
        if isinstance(item, WorkspacePerson):
            self.people[item.id] = item
        if isinstance(item, WorkspaceProject):
            self.projects[item.id] = item

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass

    async def refresh(self, item: Any) -> None:
        pass


def utterance(person_id: UUID | None = None, text: str = "사람이 고친 문장") -> dict[str, Any]:
    return {
        "id": "turn-1",
        "personId": str(person_id) if person_id else None,
        "speakerName": "민수",
        "text": text,
        "startSeconds": 0,
        "endSeconds": 2,
    }


async def directory(session: FakeSession) -> tuple[WorkspacePerson, WorkspaceProject]:
    user = AuthUser(id=OWNER)
    person = await create_person(
        WORKSPACE,
        PersonInput(name="김민수", role="개발자", aliases=["민수"]),
        user,
        session,  # type: ignore[arg-type]
    )
    project = await create_project(
        WORKSPACE,
        ProjectInput(name="맥락이", ownerPersonId=person.id),
        user,
        session,  # type: ignore[arg-type]
    )
    return person, project


async def test_meeting_can_confirm_without_a_project(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    session.source.review_utterances = [utterance()]
    calls: list[Any] = []
    monkeypatch.setattr(
        "app.api.workspaces.review.process_source.apply_async", lambda **kw: calls.append(kw)
    )
    response = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=0),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert response.status == "queued"
    assert session.source.confirmed_snapshot["projects"] == []
    assert len(calls) == 1


async def test_review_project_change_invalidates_stale_association_client() -> None:
    session = FakeSession()
    project = WorkspaceProject(workspace_id=WORKSPACE, owner_id=OWNER, name="Project")
    session.projects[project.id] = project
    await save_review(
        WORKSPACE,
        session.source.id,
        ReviewPatch(revision=0, projectIds=[project.id], utterances=[utterance()]),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert session.source.association_revision == 1
    with pytest.raises(HTTPException) as exc:
        await patch_associations(
            WORKSPACE,
            session.source.id,
            AssociationsPatch(revision=0, projectIds=[], people=[]),
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


async def test_association_change_invalidates_stale_review_client() -> None:
    session = FakeSession()
    project = WorkspaceProject(workspace_id=WORKSPACE, owner_id=OWNER, name="Project")
    session.projects[project.id] = project
    await patch_associations(
        WORKSPACE,
        session.source.id,
        AssociationsPatch(revision=0, projectIds=[project.id], people=[]),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert session.source.review_revision == 1
    with pytest.raises(HTTPException) as exc:
        await save_review(
            WORKSPACE,
            session.source.id,
            ReviewPatch(revision=0, projectIds=[], utterances=[utterance()]),
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 409


async def test_confirmed_metadata_change_preserves_review_revision_and_checkpoint() -> None:
    session = FakeSession()
    session.source.review_state = "confirmed"
    session.source.review_revision = 3
    session.source.confirmed_snapshot = {"projects": [], "people": []}
    session.source.analysis_checkpoint = {"phase": "done"}
    await patch_associations(
        WORKSPACE,
        session.source.id,
        AssociationsPatch(revision=0, projectIds=[], people=[]),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert session.source.association_revision == 1
    assert session.source.review_revision == 3
    assert session.source.confirmed_snapshot == {"projects": [], "people": []}
    assert session.source.analysis_checkpoint == {"phase": "done"}


async def test_directory_owner_person_must_belong_to_workspace() -> None:
    session = FakeSession()
    outsider = WorkspacePerson(workspace_id=OTHER, owner_id=OWNER, name="다른 팀")
    session.people[outsider.id] = outsider

    with pytest.raises(HTTPException) as error:
        await create_project(
            WORKSPACE,
            ProjectInput(name="Project", ownerPersonId=outsider.id),
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 422
    assert not session.projects


async def test_review_rejects_cross_workspace_person_and_project_refs() -> None:
    session = FakeSession()
    outsider = WorkspacePerson(workspace_id=OTHER, owner_id=OWNER, name="다른 팀")
    session.people[outsider.id] = outsider
    project = WorkspaceProject(workspace_id=OTHER, owner_id=OWNER, name="Other")
    session.projects[project.id] = project
    user = AuthUser(id=OWNER)

    for project_id, person_id in ((project.id, None), (None, outsider.id)):
        with pytest.raises(HTTPException) as error:
            await save_review(
                WORKSPACE,
                session.source.id,
                ReviewPatch(revision=0, projectId=project_id, utterances=[utterance(person_id)]),
                user,
                session,  # type: ignore[arg-type]
            )
        assert error.value.status_code == 422
    assert session.source.review_revision == 0


async def test_stale_review_is_rejected_without_a_write() -> None:
    session = FakeSession()
    session.source.review_revision = 2
    with pytest.raises(HTTPException) as error:
        await save_review(
            WORKSPACE,
            session.source.id,
            ReviewPatch(revision=1, projectId=None, utterances=[utterance()]),
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 409
    assert session.commits == 0


async def test_confirm_uses_edited_text_snapshot_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    person, project = await directory(session)
    user = AuthUser(id=OWNER)
    await save_review(
        WORKSPACE,
        session.source.id,
        ReviewPatch(revision=0, projectId=project.id, utterances=[utterance(person.id)]),
        user,
        session,  # type: ignore[arg-type]
    )
    calls: list[str] = []
    monkeypatch.setattr(
        review_module.process_source,
        "apply_async",
        lambda **kwargs: calls.append(kwargs["task_id"]),
    )

    first = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=1),
        user,
        session,  # type: ignore[arg-type]
    )
    second = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=1),
        user,
        session,  # type: ignore[arg-type]
    )

    assert first.status == second.status == "queued"
    assert calls == [str(session.source.id)]
    assert session.source.transcript_text == "김민수: 사람이 고친 문장"
    assert session.source.review_utterances[0]["speakerName"] == "김민수"
    assert session.source.confirmed_snapshot["people"][0]["id"] == str(person.id)
    assert session.source.confirmed_snapshot["people"][0]["role"] == "개발자"
    assert session.source.confirmed_snapshot["project"]["id"] == str(project.id)
    assert session.source.confirmed_snapshot["project"]["ownerName"] == "김민수"
    assert session.source.confirmed_snapshot["project"]["ownerRole"] == "개발자"


async def test_confirm_drops_blank_row_with_another_selected_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    speaker, project = await directory(session)
    other = await create_person(
        WORKSPACE,
        PersonInput(name="박지수", role="기획자"),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    session.source.project_id = project.id
    blank = {**utterance(other.id, "   "), "id": "turn-2", "speakerName": "지수"}
    session.source.review_utterances = [utterance(speaker.id), blank]
    published: list[str] = []
    monkeypatch.setattr(
        review_module.process_source,
        "apply_async",
        lambda **kwargs: published.append(kwargs["task_id"]),
    )

    result = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=0),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )

    assert result.status == "queued"
    assert published == [str(session.source.id)]
    assert session.source.transcript_text == "김민수: 사람이 고친 문장"
    assert [row["id"] for row in session.source.review_utterances] == ["turn-1"]
    assert [person["id"] for person in session.source.confirmed_snapshot["people"]] == [
        str(speaker.id)
    ]


async def test_failed_queue_enqueue_can_retry_same_confirm_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    _, project = await directory(session)
    session.source.project_id = project.id
    session.source.review_utterances = [utterance()]
    attempts = 0

    def enqueue(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError("broker down")

    monkeypatch.setattr(review_module.process_source, "apply_async", enqueue)
    user = AuthUser(id=OWNER)

    with pytest.raises(HTTPException) as error:
        await confirm_review(
            WORKSPACE,
            session.source.id,
            ConfirmRequest(revision=0),
            user,
            session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 503
    assert session.source.review_state == "confirmed"
    assert session.source.status == "failed"
    snapshot = session.source.confirmed_snapshot

    result = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=0),
        user,
        session,  # type: ignore[arg-type]
    )
    assert attempts == 2
    assert result.status == "queued"
    assert session.source.confirmed_snapshot == snapshot
    assert snapshot["people"] == []
    assert snapshot["project"]["ownerName"] == "김민수"
    assert snapshot["project"]["ownerRole"] == "개발자"


async def test_confirm_rechecks_archived_refs_and_does_not_publish() -> None:
    session = FakeSession()
    person, project = await directory(session)
    session.source.project_id = project.id
    session.source.review_utterances = [utterance(person.id)]
    person.archived_at = session.source.created_at
    before = session.commits

    with pytest.raises(HTTPException) as error:
        await confirm_review(
            WORKSPACE,
            session.source.id,
            ConfirmRequest(revision=0),
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert error.value.status_code == 422
    assert session.commits == before
    assert session.source.review_state == "awaiting_review"


async def test_publish_happens_before_source_lock_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    _, project = await directory(session)
    session.source.project_id = project.id
    session.source.review_utterances = [utterance()]
    initial_commits = session.commits
    seen: list[tuple[int, str]] = []

    def enqueue(**kwargs: Any) -> None:
        seen.append((session.commits, session.source.status))

    monkeypatch.setattr(review_module.process_source, "apply_async", enqueue)
    await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=0),
        AuthUser(id=OWNER),
        session,  # type: ignore[arg-type]
    )
    assert seen == [(initial_commits, "enqueue_pending")]
    assert session.source.status == "queued"


async def test_failed_server_stt_retries_same_audio_and_keeps_live_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    session.source.transcript_source = "server"
    session.source.review_state = "transcribing"
    session.source.status = "failed"
    session.source.processing_stage = "transcribing"
    session.source.error_message = "Provider unavailable"
    session.source.review_utterances = [utterance(text="사용자 수정본")]
    original_path = session.source.object_path
    failed_review = review_payload(session.source)
    assert (failed_review.status, failed_review.stage, failed_review.error_message) == (
        "failed",
        "transcribing",
        "Provider unavailable",
    )
    published: list[str] = []
    monkeypatch.setattr(
        review_module.process_source,
        "apply_async",
        lambda **kwargs: published.append(kwargs["task_id"]),
    )
    user = AuthUser(id=OWNER)

    first = await retry_transcription(WORKSPACE, session.source.id, user, session)  # type: ignore[arg-type]
    second = await retry_transcription(WORKSPACE, session.source.id, user, session)  # type: ignore[arg-type]

    assert first.status == second.status == "queued"
    assert published == [str(session.source.id)]
    assert session.source.object_path == original_path
    assert session.source.review_utterances[0]["text"] == "사용자 수정본"
    assert session.source.review_state == "transcribing"
    assert session.source.confirmed_snapshot is None
    failed_review = review_payload(session.source)
    assert failed_review.status == "queued"
    assert failed_review.stage == "transcribing"
    assert failed_review.error_message is None


async def test_stt_retry_rejects_confirmed_meeting_and_foreign_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    session.source.transcript_source = "server"
    session.source.review_state = "confirmed"
    session.source.status = "failed"
    monkeypatch.setattr(
        review_module.process_source,
        "apply_async",
        lambda **kwargs: pytest.fail("confirmed meeting was enqueued"),
    )
    with pytest.raises(HTTPException) as confirmed:
        await retry_transcription(
            WORKSPACE,
            session.source.id,
            AuthUser(id=OWNER),
            session,  # type: ignore[arg-type]
        )
    assert confirmed.value.status_code == 409
    with pytest.raises(HTTPException) as foreign:
        await retry_transcription(
            WORKSPACE,
            session.source.id,
            AuthUser(id=OTHER),
            session,  # type: ignore[arg-type]
        )
    assert foreign.value.status_code == 404


def test_http_contract_uses_camel_case_and_review_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    app = create_app()

    async def session_dependency() -> Any:
        yield session

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=OWNER)
    app.dependency_overrides[get_session] = session_dependency
    monkeypatch.setattr(review_module.process_source, "apply_async", lambda **kwargs: None)
    client = TestClient(app)
    base = f"/api/v1/workspaces/{WORKSPACE}"
    try:
        person = client.post(
            f"{base}/people", json={"name": "김민수", "role": "개발자", "aliases": ["민수"]}
        )
        assert person.status_code == 201
        person_id = person.json()["id"]
        assert person.json()["workspaceId"] == str(WORKSPACE)
        assert person.json()["role"] == "개발자"
        edited = client.patch(f"{base}/people/{person_id}", json={"role": "리드"})
        assert edited.status_code == 200
        assert edited.json()["role"] == "리드"

        project = client.post(
            f"{base}/projects", json={"name": "맥락이", "ownerPersonId": person_id}
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        review_url = f"{base}/sources/{session.source.id}/review"
        saved = client.patch(
            review_url,
            json={
                "revision": 0,
                "projectId": project_id,
                "utterances": [utterance(UUID(person_id))],
            },
        )
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        assert saved.json()["projectId"] == project_id
        assert saved.json()["utterances"][0]["personId"] == person_id

        confirmed = client.post(f"{review_url}/confirm", json={"revision": 1})
        assert confirmed.status_code == 202
        assert confirmed.json()["status"] == "queued"
        assert client.get(review_url).json()["reviewState"] == "confirmed"
        assert client.get(review_url).json()["confirmedSnapshot"]["project"]["ownerRole"] == "리드"
    finally:
        app.dependency_overrides.clear()


def test_http_failed_stt_review_exposes_error_and_retries_same_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    session.source.transcript_source = "server"
    session.source.review_state = "transcribing"
    session.source.status = "failed"
    session.source.processing_stage = "transcribing"
    session.source.error_message = "Provider unavailable"
    app = create_app()

    async def session_dependency() -> Any:
        yield session

    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=OWNER)
    app.dependency_overrides[get_session] = session_dependency
    published: list[str] = []
    monkeypatch.setattr(
        review_module.process_source,
        "apply_async",
        lambda **kwargs: published.append(kwargs["task_id"]),
    )
    client = TestClient(app)
    review_url = f"/api/v1/workspaces/{WORKSPACE}/sources/{session.source.id}/review"
    try:
        review = client.get(review_url)
        assert review.status_code == 200
        assert (review.json()["status"], review.json()["stage"], review.json()["errorMessage"]) == (
            "failed",
            "transcribing",
            "Provider unavailable",
        )
        first = client.post(f"{review_url}/retry-transcription")
        second = client.post(f"{review_url}/retry-transcription")
        assert first.status_code == second.status_code == 202
        assert first.json()["sourceId"] == second.json()["sourceId"] == str(session.source.id)
        assert published == [str(session.source.id)]
    finally:
        app.dependency_overrides.clear()

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import app
from app.modules.context_engine.infrastructure.models import Chunk
from app.modules.workspaces.infrastructure.models import Source

USER = uuid4()
WORKSPACE = uuid4()
MEETING = Source(
    id=uuid4(),
    workspace_id=WORKSPACE,
    owner_id=USER,
    kind="meeting",
    title="아키텍처 회의",
    object_path="a",
    content_type="text/plain",
    size_bytes=1,
)


def chunk(position: int, text: str, start: float | None = None, end: float | None = None) -> Chunk:
    return Chunk(
        id=uuid4(),
        workspace_id=WORKSPACE,
        source_id=MEETING.id,
        owner_id=USER,
        position=position,
        content=text,
        start_seconds=start,
        end_seconds=end,
    )


CHUNKS = [
    chunk(0, "박지훈: 캐시를 검토합시다.", 0.0, 42.5),
    chunk(1, "최서연: 좋습니다.", 42.5, 60.0),
]


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(self, owner: UUID, chunks: list[Chunk]) -> None:
        self.owner = owner
        self.chunks = chunks

    async def get(self, model: Any, identifier: Any) -> Source | None:
        if identifier != MEETING.id:
            return None
        return MEETING.model_copy(update={"owner_id": self.owner})

    async def exec(self, statement: Any) -> FakeResult:
        return FakeResult(self.chunks)


def serve(owner: UUID = USER, chunks: list[Chunk] | None = None) -> None:
    async def session() -> Any:
        yield FakeSession(owner, CHUNKS if chunks is None else chunks)

    app.dependency_overrides[get_session] = session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    serve()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def content(client: TestClient, source: UUID = MEETING.id) -> Any:
    return client.get(f"/api/v1/sources/{source}/content")


def test_the_content_has_the_shape_the_source_viewer_expects(client: TestClient) -> None:
    body = content(client).json()

    assert body["sourceId"] == str(MEETING.id)
    assert (body["title"], body["kind"]) == ("아키텍처 회의", "meeting")
    assert [c["text"] for c in body["chunks"]] == [
        "박지훈: 캐시를 검토합시다.",
        "최서연: 좋습니다.",
    ]
    assert set(body["chunks"][0]) >= {"id", "text"}


def test_chunk_ids_are_the_ones_evidence_points_at(client: TestClient) -> None:
    ids = [c["id"] for c in content(client).json()["chunks"]]

    assert ids == [str(c.id) for c in CHUNKS]


def test_meeting_chunks_carry_their_position_in_the_recording(client: TestClient) -> None:
    first, second = content(client).json()["chunks"]

    assert (first["startSeconds"], first["endSeconds"]) == (0.0, 42.5)
    assert second["startSeconds"] == 42.5


def test_document_chunks_have_no_timestamps(client: TestClient) -> None:
    serve(chunks=[chunk(0, "기획서 본문")])

    (only,) = content(client).json()["chunks"]

    assert (only["startSeconds"], only["endSeconds"]) == (None, None)


def test_a_source_that_is_not_indexed_yet_has_no_chunks(client: TestClient) -> None:
    serve(chunks=[])

    response = content(client)

    assert response.status_code == 200
    assert response.json()["chunks"] == []


def test_someone_elses_source_is_a_404(client: TestClient) -> None:
    serve(owner=uuid4())

    assert content(client).status_code == 404


def test_an_unknown_source_is_a_404(client: TestClient) -> None:
    assert content(client, uuid4()).status_code == 404


def test_the_path_is_registered() -> None:
    assert "/api/v1/sources/{source_id}/content" in app.openapi()["paths"]

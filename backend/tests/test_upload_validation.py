from collections.abc import Iterator
from importlib import import_module
from io import BytesIO
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import AuthUser
from app.core.database import get_session
from app.main import create_app
from app.modules.ingestion.application.upload_validation import (
    InvalidUploadError,
    UnsupportedUploadError,
    validate_document,
    validate_recording,
)
from app.modules.workspaces.infrastructure.models import Workspace

workspace_router = import_module("app.api.workspaces.router")

USER = uuid4()
WORKSPACE = uuid4()


def docx(*members: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name in members:
            archive.writestr(name, "<xml/>")
    return output.getvalue()


@pytest.mark.parametrize(
    ("name", "mime", "content"),
    [
        ("report.PDF", "application/pdf", b"%PDF-1.7\nbody"),
        (
            "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            docx("[Content_Types].xml", "_rels/.rels", "word/document.xml"),
        ),
        ("notes.txt", "text/plain; charset=utf-8", "안녕하세요\n".encode()),
        ("notes.md", "text/markdown", b"\xef\xbb\xbf# Notes\n"),
        ("notes.markdown", "text/plain", b"# Notes\n"),
    ],
)
def test_supported_documents(name: str, mime: str, content: bytes) -> None:
    validate_document(name, mime, content)


@pytest.mark.parametrize(
    ("name", "mime", "content", "error"),
    [
        ("report.exe", "application/octet-stream", b"binary", UnsupportedUploadError),
        ("report.pdf", "text/plain", b"%PDF-1.7", UnsupportedUploadError),
        ("report.pdf", "application/pdf", b"not pdf", InvalidUploadError),
        ("report.docx", "application/zip", docx("other.xml"), InvalidUploadError),
        ("report.docx", "application/zip", b"PK invalid", InvalidUploadError),
        ("notes.txt", "text/plain", b"\xff\xfe", InvalidUploadError),
        ("notes.md", "text/plain", b"a\x00b", InvalidUploadError),
    ],
)
def test_bad_documents(name: str, mime: str, content: bytes, error: type[ValueError]) -> None:
    with pytest.raises(error):
        validate_document(name, mime, content)


@pytest.mark.parametrize(
    ("name", "mime", "content", "expected"),
    [
        ("recording.webm", "audio/webm;codecs=opus", b"\x1a\x45\xdf\xa3webm", ".webm"),
        ("recording.webm", "audio/mp4", b"\x00\x00\x00\x18ftypmp42", ".mp4"),
        ("recording.mp4", "audio/mp4", b"\x00\x00\x00\x18ftypmp42", ".mp4"),
        ("recording.m4a", "audio/x-m4a", b"\x00\x00\x00\x18ftypM4A ", ".mp4"),
        ("recording.wav", "audio/wav", b"RIFF\x00\x00\x00\x00WAVE", ".wav"),
        ("recording.mp3", "audio/mpeg", b"ID3\x04\x00", ".mp3"),
        ("recording.ogg", "audio/ogg", b"OggS\x00", ".ogg"),
        ("recording.flac", "audio/flac", b"fLaC\x00", ".flac"),
    ],
)
def test_supported_recordings(name: str, mime: str, content: bytes, expected: str) -> None:
    assert validate_recording(name, mime, content) == expected


@pytest.mark.parametrize(
    ("name", "mime", "content", "error"),
    [
        ("recording.exe", "application/octet-stream", b"bad", UnsupportedUploadError),
        ("recording.webm", "audio/webm", b"bad", InvalidUploadError),
        ("recording.mp4", "audio/mp4", b"\x1a\x45\xdf\xa3", InvalidUploadError),
        ("recording.wav", "audio/mpeg", b"RIFF\x00\x00\x00\x00WAVE", InvalidUploadError),
    ],
)
def test_bad_recordings(name: str, mime: str, content: bytes, error: type[ValueError]) -> None:
    with pytest.raises(error):
        validate_recording(name, mime, content)


class FakeSession:
    def __init__(self) -> None:
        self.sources: list[Any] = []

    async def get(self, model: Any, identifier: Any) -> Workspace | None:
        if model is Workspace and identifier == WORKSPACE:
            return Workspace(id=WORKSPACE, owner_id=USER, name="test")
        return None

    def add(self, source: Any) -> None:
        self.sources.append(source)

    async def commit(self) -> None:
        pass


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, FakeSession, list[Any]]]:
    session = FakeSession()
    uploaded: list[Any] = []
    test_app = create_app()

    async def get_test_session() -> Any:
        yield session

    async def upload(source: Any, _content: bytes, _credentials: Any) -> None:
        uploaded.append(source)

    async def enqueue(_source: Any, _session: Any) -> None:
        pass

    test_app.dependency_overrides[get_current_user] = lambda: AuthUser(id=str(USER), metadata={})
    test_app.dependency_overrides[get_session] = get_test_session
    monkeypatch.setattr(workspace_router, "_upload_object", upload)
    monkeypatch.setattr(workspace_router, "_enqueue_source", enqueue)
    try:
        yield TestClient(test_app), session, uploaded
    finally:
        test_app.dependency_overrides.clear()


def test_rejected_uploads_never_reach_storage_or_queue(
    client: tuple[TestClient, FakeSession, list[Any]],
) -> None:
    http, session, uploaded = client
    for endpoint, field, file, expected in [
        ("documents", "file", ("bad.pdf", b"not pdf", "application/pdf"), 422),
        ("documents", "file", ("bad.exe", b"binary", "application/octet-stream"), 415),
        ("recordings", "audio", ("bad.webm", b"not webm", "audio/webm"), 422),
        ("recordings", "audio", ("bad.xyz", b"bad", "application/octet-stream"), 415),
    ]:
        response = http.post(
            f"/api/v1/workspaces/{WORKSPACE}/sources/{endpoint}",
            files={field: file},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == expected
    assert uploaded == session.sources == []


def test_browser_mp4_is_stored_with_matching_filename(
    client: tuple[TestClient, FakeSession, list[Any]],
) -> None:
    http, session, uploaded = client
    response = http.post(
        f"/api/v1/workspaces/{WORKSPACE}/sources/recordings",
        files={"audio": ("recording.webm", b"\x00\x00\x00\x18ftypmp42", "audio/mp4")},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 202
    assert len(uploaded) == len(session.sources) == 1
    assert uploaded[0].title == "recording.mp4"
    assert uploaded[0].content_type == "audio/mp4"

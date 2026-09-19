"""Offline contract tests for the preprocessed demo snapshot."""

import base64
import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

import app.demo_snapshot as snapshot_module
from app.demo_snapshot import (
    SnapshotError,
    Storage,
    _digest,
    _model_row,
    _row,
    restore_plan,
    restore_snapshot,
    validate_artifact,
)
from app.modules.context_engine.infrastructure.models import ContextRecord
from app.modules.workspaces.infrastructure.models import Workspace


def artifact() -> tuple[dict, UUID]:
    owner, workspace, source, chunk, context, store, node_a, node_b, edge = (
        uuid4() for _ in range(9)
    )
    data = b"processed demo document"
    common = {"workspace_id": str(workspace), "owner_id": str(owner)}
    payload = {
        "version": 1,
        "workspace": {
            "id": str(workspace),
            "owner_id": str(owner),
            "name": "Demo",
            "model_settings": {
                "embedding": {"provider": "openai", "model": "text-embedding-3-small"}
            },
            "created_at": datetime.now(UTC).isoformat(),
        },
        "sources": [
            {
                **common,
                "id": str(source),
                "kind": "document",
                "title": "demo.md",
                "object_path": f"{owner}/{workspace}/{source}/demo.md",
                "content_type": "text/markdown",
                "size_bytes": len(data),
                "status": "succeeded",
                "processing_stage": "completed",
                "progress": 1,
                "error_message": None,
            }
        ],
        "chunks": [
            {
                **common,
                "id": str(chunk),
                "source_id": str(source),
                "position": 0,
                "content": data.decode(),
                "embedding": [0.01] * 1536,
            }
        ],
        "contexts": [
            {
                **common,
                "id": str(context),
                "source_id": str(source),
                "chunk_id": str(chunk),
                "kind": "fact",
                "title": "fact",
                "body": "demo",
                "metadata": {"key": "demo"},
            }
        ],
        "context_stores": [
            {
                **common,
                "id": str(store),
                "subject": "Demo",
                "source_ids": [str(source)],
                "open_issues": [
                    {"title": "issue", "source_id": str(source), "source_refs": ["demo"]}
                ],
                "decisions": [
                    {"title": "decision", "source_id": str(source), "source_refs": ["demo"]}
                ],
                "next_actions": [
                    {"title": "action", "source_id": str(source), "source_refs": ["demo"]}
                ],
            }
        ],
        "graph": {
            "nodes": [
                {
                    "id": str(node_a),
                    "workspace_id": str(workspace),
                    "source_id": str(source),
                    "source_ids": [str(source)],
                    "chunk_id": str(chunk),
                    "kind": "Project",
                    "name": "Demo",
                },
                {
                    "id": str(node_b),
                    "workspace_id": str(workspace),
                    "source_id": str(source),
                    "source_ids": [str(source)],
                    "chunk_id": str(chunk),
                    "kind": "Issue",
                    "name": "Issue",
                },
            ],
            "edges": [
                {
                    "id": str(edge),
                    "workspace_id": str(workspace),
                    "source_id": str(source),
                    "chunk_id": str(chunk),
                    "source": str(node_a),
                    "target": str(node_b),
                    "kind": "RELATED_TO",
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_to": None,
                }
            ],
        },
        "objects": [
            {
                "source_id": str(source),
                "data": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    return {"payload": payload, "sha256": _digest(payload)}, owner


def resign(value: dict) -> dict:
    value["sha256"] = _digest(value["payload"])
    return value


def test_artifact_validation_rejects_tampering_and_cross_workspace_references() -> None:
    snapshot, owner = artifact()
    assert restore_plan(snapshot, owner)["sources"] == 1
    changed = deepcopy(snapshot)
    changed["payload"]["chunks"][0]["embedding"][0] = 0.02
    with pytest.raises(SnapshotError, match="checksum"):
        validate_artifact(changed, owner_id=owner)
    changed = resign(changed)
    changed["payload"]["chunks"][0]["source_id"] = str(uuid4())
    with pytest.raises(SnapshotError, match="checksum"):
        validate_artifact(changed, owner_id=owner)
    with pytest.raises(SnapshotError, match="owner"):
        restore_plan(snapshot, uuid4())
    changed = deepcopy(snapshot)
    changed["payload"]["workspace"]["model_settings"]["access_token"] = "never-export"
    with pytest.raises(SnapshotError, match="credential"):
        validate_artifact(resign(changed), owner_id=owner)
    for field, value in (("provider", ""), ("model", "  ")):
        changed = deepcopy(snapshot)
        changed["payload"]["workspace"]["model_settings"]["embedding"][field] = value
        with pytest.raises(SnapshotError, match=f"embedding {field}"):
            validate_artifact(resign(changed), owner_id=owner)
    changed = deepcopy(snapshot)
    del changed["payload"]["workspace"]["model_settings"]["embedding"]
    with pytest.raises(SnapshotError, match="embedding model settings"):
        validate_artifact(resign(changed), owner_id=owner)


def test_storage_create_uses_non_upsert_post() -> None:
    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return type("Response", (), {"raise_for_status": lambda self: None})()

    storage = Storage("https://storage.example", "sources", "secret")
    storage.client.close()
    storage.client = Client()
    storage.write("owner/workspace/file.md", b"source", "text/markdown")
    url, kwargs = storage.client.calls[0]
    assert url.endswith("/storage/v1/object/sources/owner/workspace/file.md")
    assert kwargs["headers"]["x-upsert"] == "false"


def test_storage_delete_uses_bucket_prefixes_contract() -> None:
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={})

    storage = Storage("https://storage.example", "sources", "secret")
    storage.client.close()
    storage.client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        storage.delete("owner/workspace/file.md")
    finally:
        storage.close()
    assert captured[0].method == "DELETE"
    assert str(captured[0].url) == "https://storage.example/storage/v1/object/sources"
    assert captured[0].read() == b'{"prefixes":["owner/workspace/file.md"]}'


def test_context_metadata_column_roundtrips() -> None:
    snapshot, _ = artifact()
    context = _model_row(ContextRecord, snapshot["payload"]["contexts"][0])
    assert context.metadata_ == {"key": "demo"}
    assert _row(context)["metadata"] == {"key": "demo"}


class FakeResult:
    def __init__(self, value):
        self.value = value

    def single(self):
        return self.value

    def consume(self):
        return None


class FakeTransaction:
    def __init__(self, graph):
        self.graph = graph

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def run(self, query, **kwargs):
        self.graph.writes.append((query, kwargs))

    def commit(self):
        self.graph.committed = True


class FakeGraph:
    def __init__(self, events=None):
        self.writes = []
        self.committed = False
        self.events = events

    def run(self, query, **kwargs):
        if "count(e) AS count" in query:
            return FakeResult({"count": 0})
        if "count(r) AS edges" in query:
            return FakeResult({"nodes": 2, "edges": 1})
        if "DETACH DELETE" in query and self.events is not None:
            self.events.append("graph_cleanup")
        self.writes.append((query, kwargs))
        return FakeResult(None)

    def begin_transaction(self):
        return FakeTransaction(self)


class FakeDb:
    def __init__(self, fail_flush=False, fail_commit=False, events=None):
        self.rows = []
        self.fail_flush = fail_flush
        self.fail_commit = fail_commit
        self.events = events
        self.committed = False
        self.rolled_back = False

    async def get(self, model, *_):
        if self.committed and model is Workspace:
            return self.rows[0]
        return None

    async def scalars(self, query):
        model = query.column_descriptions[0]["entity"]
        return FakeScalars([row for row in self.rows if isinstance(row, model)])

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        if self.events is not None:
            self.events.append("flush")
        if self.fail_flush and len(self.rows) > 1:
            raise RuntimeError("fake SQL failure")

    async def commit(self):
        if self.events is not None:
            self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("ambiguous commit")
        self.committed = True

    async def rollback(self):
        if self.events is not None:
            self.events.append("rollback")
        self.rolled_back = True


class FakeStorage:
    def __init__(self, events=None):
        self.objects = {}
        self.events = events

    def write(self, path, data, content_type):
        assert path not in self.objects
        self.objects[path] = data

    def delete(self, path):
        if self.events is not None:
            self.events.append("object_cleanup")
        del self.objects[path]

    def read(self, path):
        return self.objects[path]


class FakeScalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_restore_copies_processed_state_without_provider_calls() -> None:
    snapshot, owner = artifact()
    db, graph, storage = FakeDb(), FakeGraph(), FakeStorage()
    result = await restore_snapshot(db, graph, storage, snapshot, owner)
    assert result["execute"] and db.committed and graph.committed
    assert len(storage.objects) == 1
    assert len(db.rows) == 5
    target = UUID(result["target_workspace_id"])
    assert db.rows[0].id == target
    assert db.rows[0].model_settings == snapshot["payload"]["workspace"]["model_settings"]
    assert db.rows[-1].open_issues[0]["source_id"] == str(db.rows[1].id)
    assert db.rows[-1].decisions[0]["source_id"] == str(db.rows[1].id)
    assert db.rows[-1].next_actions[0]["source_id"] == str(db.rows[1].id)
    assert any("datetime($valid_from)" in query for query, _ in graph.writes)
    graph_writes = len(graph.writes)
    with pytest.raises(SnapshotError, match="already exists"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert len(graph.writes) == graph_writes
    assert len(db.rows) == 5 and len(storage.objects) == 1


@pytest.mark.asyncio
async def test_sql_failure_removes_only_new_graph_and_object() -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_flush=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)
    with pytest.raises(RuntimeError, match="fake SQL failure"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert db.rolled_back and not db.committed
    assert not storage.objects
    assert any("DETACH DELETE" in query for query, _ in graph.writes)
    assert events[-3:] == ["graph_cleanup", "object_cleanup", "rollback"]


@pytest.mark.asyncio
async def test_commit_error_verified_committed_preserves_external_state(monkeypatch) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_commit=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)

    async def committed(*_):
        return True

    monkeypatch.setattr(snapshot_module, "_verify_committed_target", committed)
    result = await restore_snapshot(db, graph, storage, snapshot, owner)
    assert result["commit_verified_after_error"] is True
    assert not db.rolled_back and len(storage.objects) == 1
    assert "graph_cleanup" not in events and "object_cleanup" not in events


@pytest.mark.asyncio
async def test_commit_error_unverified_preserves_external_state(monkeypatch) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_commit=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)

    async def unknown(*_):
        return None

    monkeypatch.setattr(snapshot_module, "_verify_committed_target", unknown)
    with pytest.raises(SnapshotError, match="commit outcome uncertain"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert db.rolled_back and len(storage.objects) == 1
    assert events[-1] == "rollback"
    assert "graph_cleanup" not in events and "object_cleanup" not in events

"""Offline contract tests for the preprocessed demo snapshot."""

import asyncio
import base64
import hashlib
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
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


def test_snapshot_accepts_directory_rows_and_checks_source_project_reference() -> None:
    snapshot, owner = artifact()
    workspace = snapshot["payload"]["workspace"]["id"]
    person, project = str(uuid4()), str(uuid4())
    snapshot["payload"]["people"] = [
        {
            "id": person,
            "workspace_id": workspace,
            "owner_id": str(owner),
            "name": "민수",
            "role": "개발자",
        }
    ]
    snapshot["payload"]["projects"] = [
        {
            "id": project,
            "workspace_id": workspace,
            "owner_id": str(owner),
            "name": "맥락이",
            "owner_person_id": person,
        }
    ]
    snapshot["payload"]["sources"][0]["project_id"] = project

    assert validate_artifact(resign(snapshot), owner_id=owner)["projects"][0]["id"] == project
    assert validate_artifact(snapshot, owner_id=owner)["people"][0]["role"] == "개발자"

    snapshot["payload"]["sources"][0]["project_id"] = str(uuid4())
    with pytest.raises(SnapshotError, match="Orphan source project"):
        validate_artifact(resign(snapshot), owner_id=owner)


@pytest.mark.parametrize("collection", ("open_issues", "decisions", "next_actions"))
def test_context_store_nested_source_must_exist_or_be_null(collection: str) -> None:
    snapshot, owner = artifact()
    changed = deepcopy(snapshot)
    changed["payload"]["context_stores"][0][collection][0]["source_id"] = str(uuid4())
    with pytest.raises(SnapshotError, match=f"Orphan Context Store {collection} source"):
        restore_plan(resign(changed), owner)
    changed["payload"]["context_stores"][0][collection][0]["source_id"] = None
    assert restore_plan(resign(changed), owner)["sources"] == 1


def test_context_chunk_must_belong_to_its_source() -> None:
    snapshot, owner = artifact()
    changed = deepcopy(snapshot)
    other_source = deepcopy(changed["payload"]["sources"][0])
    other_source["id"] = str(uuid4())
    other_source["object_path"] = (
        f"{owner}/{changed['payload']['workspace']['id']}/{other_source['id']}/other.md"
    )
    changed["payload"]["sources"].append(other_source)
    other_object = deepcopy(changed["payload"]["objects"][0])
    other_object["source_id"] = other_source["id"]
    changed["payload"]["objects"].append(other_object)
    changed["payload"]["context_stores"][0]["source_ids"].append(other_source["id"])
    changed["payload"]["contexts"][0]["source_id"] = other_source["id"]
    with pytest.raises(SnapshotError, match="Context chunk belongs to another source"):
        restore_plan(resign(changed), owner)


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


@pytest.mark.asyncio
async def test_absent_target_reservation_flushes_before_yield_and_rolls_back(monkeypatch) -> None:
    snapshot, _ = artifact()
    workspace = snapshot["payload"]["workspace"]
    events = []
    bind = object()
    fail_flush = False

    class ReservationSession:
        def __init__(self, *, bind: object):
            assert bind is outer_bind

        async def __aenter__(self):
            events.append("enter")
            return self

        async def __aexit__(self, *_):
            events.append("exit")

        async def execute(self, statement):
            assert str(statement) == "SET LOCAL lock_timeout = '5000ms'"
            events.append("lock_timeout")

        def add(self, row):
            assert isinstance(row, Workspace)
            events.append("add")

        async def flush(self):
            events.append("flush")
            if fail_flush:
                raise RuntimeError("flush failed")

        async def rollback(self):
            events.append("rollback")

    outer_bind = bind
    monkeypatch.setattr(snapshot_module, "AsyncSession", ReservationSession)
    async with snapshot_module._reserve_absent_target(SimpleNamespace(bind=bind), workspace):
        events.append("yield")
    assert events == ["enter", "lock_timeout", "add", "flush", "yield", "rollback", "exit"]

    events.clear()
    fail_flush = True
    with pytest.raises(RuntimeError, match="flush failed"):
        async with snapshot_module._reserve_absent_target(SimpleNamespace(bind=bind), workspace):
            events.append("yield")
    assert events == ["enter", "lock_timeout", "add", "flush", "exit"]


@pytest.mark.asyncio
async def test_committed_target_verification_timeout_is_unknown(monkeypatch) -> None:
    cancelled = asyncio.Event()

    class SlowVerifier:
        def __init__(self, *, bind: object):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, model, target):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    monkeypatch.setattr(snapshot_module, "AsyncSession", SlowVerifier)
    monkeypatch.setattr(snapshot_module, "COMMIT_SETTLE_SECONDS", 0.01)
    result = await snapshot_module._verify_committed_target(SimpleNamespace(bind=object()), uuid4())
    assert result is None and cancelled.is_set()


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


@pytest.mark.asyncio
async def test_lost_upload_response_cleans_only_this_attempt_and_retry_succeeds() -> None:
    snapshot, owner = artifact()
    graph, storage = FakeGraph(), FakeStorage()
    target = restore_plan(snapshot, owner)["target_workspace_id"]
    old_path = f"{owner}/{target}/previous-attempt/demo.md"
    storage.objects[old_path] = b"pre-existing"
    original_write = storage.write

    def lost_response(path, data, content_type):
        original_write(path, data, content_type)
        raise httpx.ReadError("upload response lost")

    storage.write = lost_response
    with pytest.raises(httpx.ReadError, match="response lost"):
        await restore_snapshot(FakeDb(), graph, storage, snapshot, owner)
    assert storage.objects == {old_path: b"pre-existing"}

    storage.write = original_write
    retry = await restore_snapshot(FakeDb(), graph, storage, snapshot, owner)
    assert retry["execute"]
    assert storage.objects[old_path] == b"pre-existing"
    assert len(storage.objects) == 2


@pytest.mark.asyncio
async def test_existing_upload_path_is_never_deleted_on_create_conflict(monkeypatch) -> None:
    snapshot, owner = artifact()
    target = restore_plan(snapshot, owner)["target_workspace_id"]
    source = snapshot["payload"]["sources"][0]
    attempt = uuid4()
    monkeypatch.setattr(snapshot_module, "uuid4", lambda: attempt)
    remapped_source = snapshot_module._remap(source["id"], UUID(target))
    path = f"{owner}/{target}/{remapped_source}/{attempt}/demo.md"
    storage = FakeStorage()
    storage.objects[path] = b"pre-existing"
    request = httpx.Request("POST", "https://storage.example/object")
    response = httpx.Response(409, request=request)

    def conflict(_path, _data, _content_type):
        raise httpx.HTTPStatusError("object exists", request=request, response=response)

    storage.write = conflict
    with pytest.raises(httpx.HTTPStatusError, match="object exists"):
        await restore_snapshot(FakeDb(), FakeGraph(), storage, snapshot, owner)
    assert storage.objects == {path: b"pre-existing"}


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
    assert db.rolled_back and len(storage.objects) == 1
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


@pytest.mark.asyncio
async def test_verified_absent_commit_cleans_under_reservation_and_allows_retry(
    monkeypatch,
) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_commit=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)
    reservation_held = False

    async def absent(*_):
        return False

    @asynccontextmanager
    async def reserve(*_):
        nonlocal reservation_held
        reservation_held = True
        events.append("reservation_acquired")
        try:
            yield
        finally:
            reservation_held = False
            events.append("reservation_released")

    original_cleanup = snapshot_module._cleanup_created_state

    def guarded_cleanup(*args):
        assert reservation_held
        return original_cleanup(*args)

    monkeypatch.setattr(snapshot_module, "_verify_committed_target", absent)
    monkeypatch.setattr(snapshot_module, "_reserve_absent_target", reserve)
    monkeypatch.setattr(snapshot_module, "_cleanup_created_state", guarded_cleanup)
    with pytest.raises(RuntimeError, match="ambiguous commit"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert db.rolled_back and not storage.objects
    assert events[-4:] == [
        "reservation_acquired",
        "graph_cleanup",
        "object_cleanup",
        "reservation_released",
    ]
    retry = await restore_snapshot(FakeDb(), graph, storage, snapshot, owner)
    assert retry["execute"] and len(storage.objects) == 1


@pytest.mark.asyncio
async def test_absent_query_without_reservation_preserves_external_state(monkeypatch) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_commit=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)

    async def absent(*_):
        return False

    @asynccontextmanager
    async def unavailable(*_):
        raise TimeoutError("reservation lock timeout")
        yield

    monkeypatch.setattr(snapshot_module, "_verify_committed_target", absent)
    monkeypatch.setattr(snapshot_module, "_reserve_absent_target", unavailable)
    with pytest.raises(SnapshotError, match="commit outcome uncertain"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert len(storage.objects) == 1
    assert "graph_cleanup" not in events and "object_cleanup" not in events


@pytest.mark.asyncio
async def test_reservation_conflict_rechecks_committed_target(monkeypatch) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(fail_commit=True, events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)
    checks = iter((False, True))

    async def verify(*_):
        return next(checks)

    @asynccontextmanager
    async def conflicting_reservation(*_):
        raise RuntimeError("unique conflict")
        yield

    monkeypatch.setattr(snapshot_module, "_verify_committed_target", verify)
    monkeypatch.setattr(snapshot_module, "_reserve_absent_target", conflicting_reservation)
    result = await restore_snapshot(db, graph, storage, snapshot, owner)
    assert result["commit_verified_after_error"] is True
    assert len(storage.objects) == 1
    assert "graph_cleanup" not in events and "object_cleanup" not in events


@pytest.mark.asyncio
async def test_late_verified_commit_reports_deadline_exceeded(monkeypatch) -> None:
    snapshot, owner = artifact()
    db, graph, storage = FakeDb(fail_commit=True), FakeGraph(), FakeStorage()
    clock = iter((0.0, 0.01, 61.0))

    async def committed(*_):
        return True

    monkeypatch.setattr(snapshot_module, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(snapshot_module, "_verify_committed_target", committed)
    result = await restore_snapshot(db, graph, storage, snapshot, owner)
    assert result["commit_verified_after_error"] is True
    assert result["deadline_exceeded"] is True
    assert result["elapsed_seconds"] == 61.0
    assert len(storage.objects) == 1


@pytest.mark.asyncio
async def test_commit_stall_uses_remaining_deadline_and_preserves_uncertain_state(
    monkeypatch,
) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)
    commit_cancelled = asyncio.Event()

    async def stalled_commit():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            commit_cancelled.set()
            raise

    async def unknown(*_):
        return None

    db.commit = stalled_commit
    monkeypatch.setattr(snapshot_module, "MAX_RESTORE_SECONDS", 0.1)
    monkeypatch.setattr(snapshot_module, "_verify_committed_target", unknown)
    with pytest.raises(SnapshotError, match="commit outcome uncertain"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert commit_cancelled.is_set() and db.rolled_back
    assert len(storage.objects) == 1
    assert "graph_cleanup" not in events and "object_cleanup" not in events


@pytest.mark.asyncio
async def test_late_successful_commit_reports_deadline_and_preserves_data(monkeypatch) -> None:
    snapshot, owner = artifact()
    events = []
    db = FakeDb(events=events)
    graph, storage = FakeGraph(events), FakeStorage(events)
    clock = iter((0.0, 0.01, 61.0))
    monkeypatch.setattr(snapshot_module, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(SnapshotError, match="after SQL commit; data preserved"):
        await restore_snapshot(db, graph, storage, snapshot, owner)
    assert db.committed and not db.rolled_back
    assert len(storage.objects) == 1
    assert "graph_cleanup" not in events and "object_cleanup" not in events

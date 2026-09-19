"""Offline contract checks for the demo smoke runner."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.demo_smoke import DEFAULT_MANIFEST, DemoSmoke, SmokeFailure, load_manifest
from tests.seeds import SEEDS

WORKSPACE = str(uuid4())


def client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(base_url="https://example.test/api/v1/", transport=handler)


def sse(*events: dict[str, object] | str) -> httpx.Response:
    frames = [
        "data: " + (event if isinstance(event, str) else json.dumps(event)) for event in events
    ]
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="\n\n".join(frames) + "\n\n",
    )


def test_manifest_points_to_the_exact_test_seed_texts() -> None:
    question, sources = load_manifest(DEFAULT_MANIFEST)
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert question == "Redis를 왜 도입했나요?"
    assert len(sources) == len(SEEDS) == 4
    for item, seed, loaded in zip(manifest["sources"], SEEDS, sources, strict=True):
        path = DEFAULT_MANIFEST.parent / item["file"]
        assert path.is_file()
        assert path.suffix == (".txt" if seed.kind == "meeting" else ".md")
        assert path.read_bytes() == seed.text.encode("utf-8")
        assert (item["id"], item["kind"], item["title"]) == (
            seed.name,
            seed.kind,
            seed.title,
        )
        assert loaded["text"] == seed.text


def test_manifest_rejects_a_path_outside_its_directory(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "question": "why?",
                "sources": [
                    {"id": "escaped", "kind": "document", "title": "bad", "file": "../outside.md"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SmokeFailure, match="escapes manifest directory"):
        load_manifest(manifest)


def test_full_run_and_rerun_reuse_the_four_sources() -> None:
    question, seeds = load_manifest(DEFAULT_MANIFEST)
    posted: list[dict[str, str]] = []
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        calls.append((request.method, path))
        if path in {"/ready", f"/workspaces/{WORKSPACE}"}:
            return httpx.Response(200, json={"ok": True})
        if path == f"/workspaces/{WORKSPACE}/sources":
            return httpx.Response(200, json=posted)
        if path.endswith("/sources/documents") or path.endswith("/sources/transcripts"):
            seed = seeds[len(posted)]
            identifier = str(uuid4())
            posted.append({"id": identifier, "title": seed["title"], "kind": seed["kind"]})
            return httpx.Response(202, json={"sourceId": identifier})
        if path.startswith("/jobs/"):
            identifier = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200, json={"sourceId": identifier, "status": "succeeded", "stage": "completed"}
            )
        if path.endswith("/content"):
            identifier = path.split("/")[2]
            return httpx.Response(200, json={"chunks": [{"id": f"chunk-{identifier}"}]})
        if path == f"/workspaces/{WORKSPACE}/context":
            return httpx.Response(200, json=[{"sources": [{"id": s["id"]} for s in posted]}])
        if path == f"/workspaces/{WORKSPACE}/context-store":
            return httpx.Response(200, json={"sourceIds": [s["id"] for s in posted]})
        if path == f"/workspaces/{WORKSPACE}/graph":
            return httpx.Response(
                200,
                json={
                    "nodes": [
                        {"id": "n1", "sources": [{"id": posted[0]["id"]}]},
                        {"id": "n2", "sources": [{"id": posted[1]["id"]}]},
                    ],
                    "edges": [{"source": "n1", "target": "n2"}],
                },
            )
        if path == f"/workspaces/{WORKSPACE}/ask":
            identifier = posted[0]["id"]
            return sse(
                {
                    "type": "sources",
                    "sources": [
                        {"index": 1, "sourceId": identifier, "chunkId": f"chunk-{identifier}"}
                    ],
                },
                {"type": "token", "text": "Redis는 성능을 위해 도입했습니다[1]."},
                {"type": "done"},
                "[DONE]",
            )
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    with client(httpx.MockTransport(handler)) as http:
        first = DemoSmoke(http, WORKSPACE).run(question, seeds)
        second = DemoSmoke(http, WORKSPACE).run(question, seeds)

    assert first["status"] == second["status"] == "passed"
    assert len(posted) == 4
    assert [s["reused"] for s in first["sources"]] == [False] * 4
    assert [s["reused"] for s in second["sources"]] == [True] * 4
    assert len([call for call in calls if call[0] == "POST" and "/sources/" in call[1]]) == 4
    assert second["checks"] == [
        "readiness_and_workspace",
        "sources_processed",
        "indexed_content",
        "context_and_graph",
        "answer_with_resolvable_citations",
    ]


@pytest.mark.parametrize("status", ["failed", "queued"])
def test_job_failure_or_timeout_is_reported(status: str) -> None:
    identifier = str(uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/jobs/{identifier}"
        return httpx.Response(200, json={"sourceId": identifier, "status": status})

    with client(httpx.MockTransport(handler)) as http:
        smoke = DemoSmoke(http, WORKSPACE, timeout=0, interval=0)
        expected = "Processing failed" if status == "failed" else "Timed out"
        with pytest.raises(SmokeFailure, match=expected):
            smoke.wait(identifier)


@pytest.mark.parametrize(
    ("events", "chunk_id", "message"),
    [
        ([{"type": "error", "message": "provider failed"}, "[DONE]"], "chunk-1", "error event"),
        ([{"type": "sources", "sources": []}, {"type": "done"}], "chunk-1", "incomplete"),
        (
            [
                {
                    "type": "sources",
                    "sources": [{"index": 1, "sourceId": "source-1", "chunkId": "chunk-1"}],
                },
                {"type": "token", "text": "근거 없는 답변"},
                {"type": "done"},
                "[DONE]",
            ],
            "chunk-1",
            "missing or invalid citations",
        ),
        (
            [
                {
                    "type": "sources",
                    "sources": [{"index": 1, "sourceId": "source-1", "chunkId": "missing"}],
                },
                {"type": "token", "text": "근거가 있습니다[1]."},
                {"type": "done"},
                "[DONE]",
            ],
            "chunk-1",
            "does not resolve",
        ),
    ],
)
def test_answer_rejects_bad_stream_or_reference(
    events: list[dict[str, object] | str], chunk_id: str, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ask"):
            return sse(*events)
        assert request.url.path == "/api/v1/sources/source-1/content"
        return httpx.Response(200, json={"chunks": [{"id": chunk_id}]})

    with (
        client(httpx.MockTransport(handler)) as http,
        pytest.raises(SmokeFailure, match=message),
    ):
        DemoSmoke(http, WORKSPACE).answer("Redis?", {"source-1"})

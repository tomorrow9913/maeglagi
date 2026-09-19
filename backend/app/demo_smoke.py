"""Repeatable API smoke check: python -m app.demo_smoke --help."""

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2] / "contracts/seeds/redis-adoption/manifest.json"
)


class SmokeFailure(RuntimeError):
    pass


def require(condition: Any, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def load_manifest(path: Path) -> tuple[str, list[dict[str, str]]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    seeds = []
    identifiers: set[str] = set()
    for item in manifest["sources"]:
        identifier = item["id"]
        require(re.fullmatch(r"[a-z0-9-]+", identifier), "Invalid seed identifier")
        require(identifier not in identifiers, "Duplicate seed identifier")
        identifiers.add(identifier)
        require(item["kind"] in {"document", "meeting"}, "Unsupported seed kind")
        file = (path.parent / item["file"]).resolve()
        require(file.is_relative_to(path.parent.resolve()), "Seed path escapes manifest directory")
        text = file.read_text(encoding="utf-8")
        require(text.strip(), f"Empty seed: {identifier}")
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        suffix = ".md" if item["kind"] == "document" else ""
        title = f"[demo-{identifier}-{digest}] {item['title']}{suffix}"
        require(len(title) <= 255, "Seed title is too long")
        seeds.append({"id": identifier, "kind": item["kind"], "title": title, "text": text})
    require(seeds, "Manifest has no sources")
    require(
        isinstance(manifest["question"], str) and manifest["question"].strip(), "Empty question"
    )
    return manifest["question"], seeds


class DemoSmoke:
    def __init__(
        self, client: httpx.Client, workspace: str, *, timeout: float = 600, interval: float = 2
    ) -> None:
        self.client = client
        self.workspace = workspace
        self.prefix = f"/workspaces/{workspace}"
        self.timeout = timeout
        self.interval = interval
        self.report: dict[str, Any] = {"workspaceId": workspace, "checks": [], "sources": []}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        # Relative paths retain the configured /api/v1 base path.
        response = self.client.request(method, path.lstrip("/"), **kwargs)
        if not response.is_success:
            # Never include response bodies, which may contain provider or storage secrets.
            raise SmokeFailure(f"{method} {path}: HTTP {response.status_code}")
        return response.json()

    def wait(self, source_id: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            job = self.request("GET", f"/jobs/{source_id}")
            require(job.get("sourceId") == source_id, "Job returned a different source")
            if job["status"] == "succeeded":
                require(job.get("stage") == "completed", "Successful job has incomplete stage")
                return
            require(job["status"] != "failed", f"Processing failed for source {source_id}")
            require(job["status"] in {"queued", "processing"}, "Unexpected job status")
            remaining = deadline - time.monotonic()
            require(remaining > 0, f"Timed out processing source {source_id}")
            time.sleep(min(self.interval, remaining))

    def seed(self, seeds: list[dict[str, str]]) -> set[str]:
        existing = self.request("GET", self.prefix + "/sources")
        result: set[str] = set()
        for seed in seeds:
            matches = [s for s in existing if s["title"] == seed["title"]]
            require(len(matches) <= 1, f"Duplicate demo source: {seed['id']}")
            if matches:
                require(matches[0]["kind"] == seed["kind"], "Existing seed has wrong kind")
                source_id = matches[0]["id"]
                reused = True
            else:
                if seed["kind"] == "document":
                    job = self.request(
                        "POST",
                        self.prefix + "/sources/documents",
                        files={"file": (seed["title"], seed["text"].encode(), "text/markdown")},
                    )
                else:
                    job = self.request(
                        "POST",
                        self.prefix + "/sources/transcripts",
                        json={"title": seed["title"], "text": seed["text"]},
                    )
                source_id = job["sourceId"]
                reused = False
            self.report["sources"].append(
                {"seed": seed["id"], "sourceId": source_id, "reused": reused}
            )
            # Sequential completion preserves the scenario's context-update order.
            self.wait(source_id)
            result.add(source_id)
        return result

    def answer(self, question: str, source_ids: set[str]) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []
        pieces: list[str] = []
        seen_sources = done = terminated = False
        with self.client.stream(
            "POST", (self.prefix + "/ask").lstrip("/"), json={"question": question}
        ) as response:
            require(response.is_success, f"Ask: HTTP {response.status_code}")
            require(
                response.headers.get("content-type", "").startswith("text/event-stream"),
                "Ask did not return SSE",
            )
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    terminated = True
                    break
                event = json.loads(data)
                require(not done, "Ask emitted an event after done")
                kind = event.get("type")
                require(kind != "error", "Ask returned an error event")
                if kind == "sources":
                    require(not seen_sources and not pieces, "Ask sources are out of order")
                    sources = event["sources"]
                    seen_sources = True
                elif kind == "token":
                    require(seen_sources, "Ask token preceded sources")
                    pieces.append(event["text"])
                elif kind == "done":
                    done = True
                else:
                    raise SmokeFailure("Unknown Ask event")
        text = "".join(pieces)
        require(done and terminated and text.strip(), "Ask stream was incomplete or empty")
        by_index = {s["index"]: s for s in sources}
        require(len(by_index) == len(sources), "Duplicate evidence index")
        cited = {
            int(number)
            for citation in re.findall(r"\[([0-9, ]+)\]", text)
            for number in re.findall(r"\d+", citation)
        }
        require(cited and cited <= by_index.keys(), "Answer has missing or invalid citations")
        require(
            any(by_index[i]["sourceId"] in source_ids for i in cited),
            "Answer did not cite a demo source",
        )
        for index in cited:
            reference = by_index[index]
            content = self.request("GET", f"/sources/{reference['sourceId']}/content")
            require(
                any(c["id"] == reference["chunkId"] for c in content["chunks"]),
                "Answer citation does not resolve to its source chunk",
            )
        return {"text": text, "sources": sources}

    def run(self, question: str, seeds: list[dict[str, str]]) -> dict[str, Any]:
        self.request("GET", "/ready")
        self.request("GET", self.prefix)
        self.report["checks"].append("readiness_and_workspace")
        source_ids = self.seed(seeds)
        self.report["checks"].append("sources_processed")
        for source_id in source_ids:
            content = self.request("GET", f"/sources/{source_id}/content")
            require(content["chunks"], f"Source has no indexed chunks: {source_id}")
        self.report["checks"].append("indexed_content")
        timeline = self.request("GET", self.prefix + "/context")
        store = self.request("GET", self.prefix + "/context-store")
        require(
            source_ids <= {s["id"] for item in timeline for s in item["sources"]},
            "Timeline does not cover all demo sources",
        )
        require(store and source_ids <= set(store["sourceIds"]), "Context store is incomplete")
        graph = self.request("GET", self.prefix + "/graph")
        demo_nodes = {
            node["id"]
            for node in graph["nodes"]
            if any(s["id"] in source_ids for s in node["sources"])
        }
        require(
            any(e["source"] in demo_nodes and e["target"] in demo_nodes for e in graph["edges"]),
            "Graph has no relation between demo nodes",
        )
        self.report["checks"].append("context_and_graph")
        self.report["answer"] = self.answer(question, source_ids)
        self.report["checks"].append("answer_with_resolvable_citations")
        self.report["status"] = "passed"
        return self.report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1/")
    parser.add_argument("--workspace", type=UUID)
    parser.add_argument(
        "--execute", action="store_true", help="Upload seeds and call real providers"
    )
    parser.add_argument("--timeout", type=float, default=600, help="Processing timeout per source")
    parser.add_argument("--report", type=Path, help="Write JSON evidence, including answer text")
    args = parser.parse_args()
    report: dict[str, Any] = {}
    try:
        question, seeds = load_manifest(args.manifest)
        require(args.timeout > 0, "Timeout must be positive")
        if not args.execute:
            report = {
                "status": "dry_run",
                "question": question,
                "sources": [{k: v for k, v in seed.items() if k != "text"} for seed in seeds],
            }
        else:
            token = os.environ.get("MAEGLAGI_ACCESS_TOKEN", "")
            require(args.workspace and token, "--workspace and MAEGLAGI_ACCESS_TOKEN are required")
            with httpx.Client(
                base_url=args.base_url.rstrip("/") + "/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            ) as client:
                smoke = DemoSmoke(client, str(args.workspace), timeout=args.timeout)
                report = smoke.report
                smoke.run(question, seeds)
    except (SmokeFailure, httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
        report["status"] = "failed"
        report["error"] = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 1 if report.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

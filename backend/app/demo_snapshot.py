"""Export and restore a processed demo workspace without invoking AI providers.

Run ``python -m app.demo_snapshot --help``. Connections are supplied explicitly through
environment variable *names*; this module never loads application settings or .env files.
The artifact contains source contents and may contain private workspace data. Store it securely.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid5

import httpx
from neo4j import GraphDatabase
from sqlalchemy import DateTime, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.workspaces.infrastructure.models import Source, Workspace

TABLES = (Source, Chunk, ContextRecord, ContextStoreRecord)
MAX_ARTIFACT_BYTES = 25_000_000
MAX_RESTORE_SECONDS = 60
VERSION = 1


class SnapshotError(ValueError):
    """Invalid or unsafe demo snapshot operation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def _json(value: Any) -> Any:
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _row(item: Any) -> dict[str, Any]:
    return {
        attribute.columns[0].name: _json(getattr(item, attribute.key))
        for attribute in inspect(type(item)).column_attrs
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SnapshotError(f"Invalid {label}") from exc


def _ids(rows: list[dict[str, Any]], label: str) -> set[str]:
    values = [_uuid(row.get("id"), label) for row in rows]
    _require(len(values) == len(set(values)), f"Duplicate {label}")
    return set(values)


def _assert_no_secret_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _require(
                str(key).lower()
                not in {
                    "api_key",
                    "access_token",
                    "refresh_token",
                    "password",
                    "secret",
                    "encrypted_secret",
                    "vault_secret_id",
                },
                "Snapshot includes a credential field",
            )
            _assert_no_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_keys(item)


def validate_artifact(artifact: dict[str, Any], *, owner_id: UUID | None = None) -> dict[str, Any]:
    """Validate the entire restore input before any write or connection is opened."""
    _require(isinstance(artifact, dict), "Artifact must be an object")
    _require(set(artifact) == {"payload", "sha256"}, "Unexpected artifact fields")
    payload = artifact["payload"]
    _require(isinstance(payload, dict), "Invalid payload")
    _require(len(_canonical(payload)) <= MAX_ARTIFACT_BYTES, "Artifact exceeds size limit")
    _require(artifact["sha256"] == _digest(payload), "Artifact checksum mismatch")
    _require(
        set(payload)
        == {
            "version",
            "workspace",
            "sources",
            "chunks",
            "contexts",
            "context_stores",
            "graph",
            "objects",
        },
        "Unexpected payload fields",
    )
    _require(payload["version"] == VERSION, "Unsupported artifact version")
    workspace = payload["workspace"]
    _require(isinstance(workspace, dict), "Invalid workspace")
    workspace_id = _uuid(workspace.get("id"), "workspace ID")
    owner = _uuid(workspace.get("owner_id"), "owner ID")
    if owner_id is not None:
        _require(owner == str(owner_id), "Snapshot owner mismatch")
    _require(
        isinstance(workspace.get("name"), str) and workspace["name"].strip(),
        "Invalid workspace name",
    )
    model_settings = workspace.get("model_settings")
    _require(isinstance(model_settings, dict), "Missing model settings")
    _assert_no_secret_keys(model_settings)
    embedding = model_settings.get("embedding")
    _require(isinstance(embedding, dict), "Missing embedding model settings")
    for key in ("provider", "model"):
        _require(
            isinstance(embedding.get(key), str) and bool(embedding[key].strip()),
            f"Missing embedding {key}",
        )
    for key in ("sources", "chunks", "contexts", "context_stores", "objects"):
        _require(isinstance(payload[key], list), f"Invalid {key}")
    sources, chunks, contexts, stores = (
        payload[key] for key in ("sources", "chunks", "contexts", "context_stores")
    )
    _require(
        bool(sources and chunks and contexts) and len(stores) == 1,
        "Incomplete processed demo state",
    )
    source_ids, chunk_ids = _ids(sources, "source ID"), _ids(chunks, "chunk ID")
    _ids(contexts, "context ID")
    _ids(stores, "context store ID")
    for key, rows in (
        ("sources", sources),
        ("chunks", chunks),
        ("contexts", contexts),
        ("context_stores", stores),
    ):
        for row in rows:
            _require(isinstance(row, dict), f"Invalid {key} row")
            _require(
                _uuid(row.get("workspace_id"), "row workspace ID") == workspace_id,
                "Workspace mismatch",
            )
            _require(_uuid(row.get("owner_id"), "row owner ID") == owner, "Owner mismatch")
    for source in sources:
        _require(
            source.get("status") == "succeeded" and source.get("processing_stage") == "completed",
            "Source is not fully processed",
        )
        _require(source.get("error_message") is None, "Source has an error")
        _require(
            isinstance(source.get("object_path"), str) and source["object_path"],
            "Missing object path",
        )
        _require(Path(source["object_path"]).name not in {"", ".", ".."}, "Invalid object path")
        _require(
            source["object_path"].startswith(f"{owner}/{workspace_id}/{source['id']}/"),
            "Source object path mismatch",
        )
    for chunk in chunks:
        _require(_uuid(chunk.get("source_id"), "chunk source ID") in source_ids, "Orphan chunk")
        embedding = chunk.get("embedding")
        _require(isinstance(embedding, list) and len(embedding) == 1536, "Missing real embedding")
        _require(
            all(
                isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < float("inf")
                for x in embedding
            ),
            "Invalid embedding",
        )
    for context in contexts:
        _require(
            _uuid(context.get("source_id"), "context source ID") in source_ids, "Orphan context"
        )
        if context.get("chunk_id") is not None:
            _require(
                _uuid(context["chunk_id"], "context chunk ID") in chunk_ids, "Orphan context chunk"
            )
    store = stores[0]
    _require(set(store.get("source_ids", [])) == source_ids, "Context Store sources mismatch")
    objects = payload["objects"]
    _require(
        {item.get("source_id") for item in objects} == source_ids and len(objects) == len(sources),
        "Missing source objects",
    )
    for item in objects:
        _require(isinstance(item.get("data"), str), "Invalid object content")
        try:
            binary = base64.b64decode(item["data"], validate=True)
        except ValueError as exc:
            raise SnapshotError("Invalid object encoding") from exc
        _require(
            hashlib.sha256(binary).hexdigest() == item.get("sha256"), "Object checksum mismatch"
        )
    graph = payload["graph"]
    _require(isinstance(graph, dict) and set(graph) == {"nodes", "edges"}, "Invalid graph")
    _require(bool(graph["nodes"] and graph["edges"]), "Incomplete graph")
    node_ids = _ids(graph["nodes"], "graph node ID")
    for node in graph["nodes"]:
        _require(node.get("workspace_id") == workspace_id, "Graph workspace mismatch")
        _require(set(node.get("source_ids", [])) <= source_ids, "Graph source mismatch")
        _require(node.get("source_id") in source_ids, "Graph evidence source mismatch")
        _require(
            node.get("chunk_id") is None or node["chunk_id"] in chunk_ids,
            "Graph evidence chunk mismatch",
        )
        _require(
            node.get("superseded_by") is None or node["superseded_by"] in node_ids,
            "Graph supersession mismatch",
        )
    edge_ids = _ids(graph["edges"], "graph edge ID")
    _require(len(edge_ids) == len(graph["edges"]), "Duplicate graph edge")
    for edge in graph["edges"]:
        _require(edge.get("workspace_id") == workspace_id, "Graph edge workspace mismatch")
        _require(
            edge.get("source") in node_ids and edge.get("target") in node_ids, "Orphan graph edge"
        )
        _require(
            edge.get("kind") in {kind.value for kind in RelationKind}, "Unsupported graph edge"
        )
        _require(edge.get("source_id") in source_ids, "Graph edge evidence source mismatch")
        _require(
            edge.get("chunk_id") is None or edge["chunk_id"] in chunk_ids,
            "Graph edge evidence chunk mismatch",
        )
    return payload


def _remap(value: str | None, target: UUID) -> str | None:
    return str(uuid5(target, value)) if value else None


def restore_plan(artifact: dict[str, Any], owner_id: UUID) -> dict[str, Any]:
    payload = validate_artifact(artifact, owner_id=owner_id)
    target = uuid5(owner_id, f"demo-snapshot-v1:{artifact['sha256']}")
    return {
        "target_workspace_id": str(target),
        "owner_id": str(owner_id),
        "sources": len(payload["sources"]),
        "chunks": len(payload["chunks"]),
        "contexts": len(payload["contexts"]),
        "nodes": len(payload["graph"]["nodes"]),
        "edges": len(payload["graph"]["edges"]),
        "objects": len(payload["objects"]),
        "execute": False,
    }


class Storage:
    def __init__(self, url: str, bucket: str, key: str) -> None:
        self.url, self.bucket, self.key = url.rstrip("/"), bucket, key
        self.client = httpx.Client(
            timeout=15, headers={"apikey": key, "Authorization": f"Bearer {key}"}
        )

    def _url(self, path: str, *, authenticated: bool = False) -> str:
        prefix = "authenticated/" if authenticated else ""
        root = f"{self.url}/storage/v1/object/{prefix}{quote(self.bucket, safe='')}"
        return f"{root}/{quote(path, safe='/')}"

    def read(self, path: str) -> bytes:
        response = self.client.get(self._url(path, authenticated=True))
        response.raise_for_status()
        return response.content

    def write(self, path: str, data: bytes, content_type: str) -> None:
        response = self.client.post(
            self._url(path),
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )
        response.raise_for_status()

    def delete(self, path: str) -> None:
        response = self.client.request(
            "DELETE", self._url("").rstrip("/"), json={"prefixes": [path]}
        )
        response.raise_for_status()

    def close(self) -> None:
        self.client.close()


async def export_snapshot(
    db: AsyncSession, graph: Any, storage: Storage, source_workspace: UUID, owner_id: UUID
) -> dict[str, Any]:
    workspace = await db.get(Workspace, source_workspace)
    _require(
        workspace is not None and workspace.owner_id == owner_id, "Source workspace owner mismatch"
    )
    rows: dict[str, list[dict[str, Any]]] = {}
    for model in TABLES:
        result = (
            await db.scalars(
                select(model).where(
                    model.workspace_id == source_workspace, model.owner_id == owner_id
                )
            )
        ).all()
        rows[model.__tablename__] = [_row(item) for item in result]
    nodes = [
        dict(item["props"])
        for item in graph.run(
            "MATCH (e:Entity {workspace_id: $workspace}) RETURN properties(e) AS props",
            workspace=str(source_workspace),
        )
    ]
    edges = []
    for item in graph.run(
        "MATCH (a:Entity {workspace_id: $workspace})-[r]->"
        "(b:Entity {workspace_id: $workspace}) "
        "RETURN a.id AS source, b.id AS target, type(r) AS kind, properties(r) AS props",
        workspace=str(source_workspace),
    ):
        edges.append(
            {
                **_json(dict(item["props"])),
                "source": item["source"],
                "target": item["target"],
                "kind": item["kind"],
            }
        )
    objects = []
    for source in rows["sources"]:
        data = storage.read(source["object_path"])
        objects.append(
            {
                "source_id": source["id"],
                "data": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    payload = {
        "version": VERSION,
        "workspace": _row(workspace),
        "sources": rows["sources"],
        "chunks": rows["chunks"],
        "contexts": rows["contexts"],
        "context_stores": rows["context_stores"],
        "graph": {"nodes": _json(nodes), "edges": _json(edges)},
        "objects": objects,
    }
    artifact = {"payload": payload, "sha256": _digest(payload)}
    validate_artifact(artifact, owner_id=owner_id)
    return artifact


def _model_row(model: Any, row: dict[str, Any]) -> Any:
    values = {}
    for attribute in inspect(model).column_attrs:
        column = attribute.columns[0]
        if column.name in row:
            value = row[column.name]
            if column.name in {"id", "workspace_id", "source_id", "chunk_id", "owner_id"}:
                value = UUID(value) if value is not None else None
            elif isinstance(column.type, DateTime) and value is not None:
                value = datetime.fromisoformat(value)
            values[attribute.key] = value
    return model(**values)


async def _verify_committed_target(db: AsyncSession, target: UUID) -> bool | None:
    """Use an independent connection; the failed session's identity map proves nothing."""
    try:
        async with AsyncSession(bind=db.bind) as verifier:
            return await verifier.get(Workspace, target) is not None
    except Exception:
        return None


async def restore_snapshot(
    db: AsyncSession, graph: Any, storage: Storage, artifact: dict[str, Any], owner_id: UUID
) -> dict[str, Any]:
    plan = restore_plan(artifact, owner_id)
    payload = artifact["payload"]
    target = UUID(plan["target_workspace_id"])
    _require(
        await db.get(Workspace, target) is None,
        "Target workspace already exists; refusing restore",
    )
    started = time.monotonic()
    paths: list[str] = []
    graph_created = False
    commit_attempted = False
    committed = False
    workspace = dict(payload["workspace"])
    workspace.update(
        id=str(target), name=f"{workspace['name'][:109]} (restored)", owner_id=str(owner_id)
    )
    try:
        db.add(_model_row(Workspace, workspace))
        await db.flush()  # Hold the target reservation through external cleanup.
        preexisting = graph.run(
            "MATCH (e:Entity {workspace_id: $workspace}) RETURN count(e) AS count",
            workspace=str(target),
        ).single()
        _require(
            preexisting is not None and preexisting["count"] == 0,
            "Target graph is not empty",
        )
        for source in payload["sources"]:
            obj = next(item for item in payload["objects"] if item["source_id"] == source["id"])
            filename = Path(source["object_path"]).name
            path = f"{owner_id}/{target}/{_remap(source['id'], target)}/{filename}"
            storage.write(path, base64.b64decode(obj["data"]), source["content_type"])
            paths.append(path)
        with graph.begin_transaction() as tx:
            for node in payload["graph"]["nodes"]:
                props = dict(node)
                props.update(
                    id=_remap(node["id"], target),
                    workspace_id=str(target),
                    source_id=_remap(node["source_id"], target),
                    chunk_id=_remap(node.get("chunk_id"), target),
                    source_ids=[_remap(item, target) for item in node["source_ids"]],
                    superseded_by=_remap(node.get("superseded_by"), target),
                )
                tx.run(
                    "CREATE (e:Entity {id: $id, workspace_id: $workspace}) SET e += $props",
                    id=props["id"],
                    workspace=str(target),
                    props={key: value for key, value in props.items() if value is not None},
                )
            for edge in payload["graph"]["edges"]:
                props = {
                    key: value
                    for key, value in edge.items()
                    if key not in {"source", "target", "kind"}
                }
                props.update(
                    id=_remap(edge["id"], target),
                    workspace_id=str(target),
                    source_id=_remap(edge["source_id"], target),
                    chunk_id=_remap(edge.get("chunk_id"), target),
                )
                kind = edge["kind"]  # validated against fixed RelationKind enum
                tx.run(
                    f"MATCH (a:Entity {{id: $source, workspace_id: $workspace}}), "
                    f"(b:Entity {{id: $target, workspace_id: $workspace}}) "
                    f"CREATE (a)-[r:{kind}]->(b) SET r += $props "
                    "SET r.valid_from = CASE WHEN $valid_from IS NULL THEN null "
                    "ELSE datetime($valid_from) END, "
                    "r.valid_to = CASE WHEN $valid_to IS NULL THEN null "
                    "ELSE datetime($valid_to) END",
                    source=_remap(edge["source"], target),
                    target=_remap(edge["target"], target),
                    workspace=str(target),
                    props={key: value for key, value in props.items() if value is not None},
                    valid_from=edge.get("valid_from"),
                    valid_to=edge.get("valid_to"),
                )
            graph_created = True
            tx.commit()
        for model, key in (
            (Source, "sources"),
            (Chunk, "chunks"),
            (ContextRecord, "contexts"),
            (ContextStoreRecord, "context_stores"),
        ):
            for original in payload[key]:
                row = dict(original)
                row.update(
                    id=_remap(original["id"], target),
                    workspace_id=str(target),
                    owner_id=str(owner_id),
                )
                if key == "sources":
                    row["object_path"] = (
                        f"{owner_id}/{target}/{row['id']}/{Path(original['object_path']).name}"
                    )
                if key in {"chunks", "contexts"}:
                    row["source_id"] = _remap(original["source_id"], target)
                if key == "contexts":
                    row["chunk_id"] = _remap(original.get("chunk_id"), target)
                if key == "context_stores":
                    row["source_ids"] = [_remap(item, target) for item in original["source_ids"]]
                    for collection in ("open_issues", "decisions", "next_actions"):
                        row[collection] = [
                            {**item, "source_id": _remap(item.get("source_id"), target)}
                            for item in original[collection]
                        ]
                db.add(_model_row(model, row))
            await db.flush()
        _require(
            time.monotonic() - started < MAX_RESTORE_SECONDS, "Restore exceeded one-minute limit"
        )
        commit_attempted = True
        await db.commit()
        committed = True
    except Exception as original:
        if commit_attempted:
            verified = await _verify_committed_target(db, target)
            if verified is True:
                committed = True
                return {
                    **plan,
                    "execute": True,
                    "commit_verified_after_error": True,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                }
            raise SnapshotError(
                "SQL commit outcome uncertain; graph and objects preserved for inspection"
            ) from original
        cleanup_errors = []
        if graph_created:
            try:
                graph.run(
                    "MATCH (e:Entity {workspace_id: $workspace}) DETACH DELETE e",
                    workspace=str(target),
                ).consume()
            except Exception:
                cleanup_errors.append("graph")
        for path in paths:
            try:
                storage.delete(path)
            except Exception:
                cleanup_errors.append("object")
        if cleanup_errors:
            raise SnapshotError(
                f"Restore failed; residual cleanup failed for {', '.join(cleanup_errors)}"
            ) from original
        raise
    finally:
        if not committed:
            await db.rollback()
    return {**plan, "execute": True, "elapsed_seconds": round(time.monotonic() - started, 2)}


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    _require(bool(value), f"Required environment variable is unset: {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "restore"))
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=UUID)
    parser.add_argument("--source-workspace", type=UUID)
    parser.add_argument("--execute", action="store_true", help="Permit infrastructure writes/reads")
    parser.add_argument("--database-url-env", default="DEMO_DATABASE_URL")
    parser.add_argument("--neo4j-url-env", default="DEMO_NEO4J_URL")
    parser.add_argument("--neo4j-user-env", default="DEMO_NEO4J_USER")
    parser.add_argument("--neo4j-password-env", default="DEMO_NEO4J_PASSWORD")
    parser.add_argument("--storage-url-env", default="DEMO_STORAGE_URL")
    parser.add_argument("--storage-key-env", default="DEMO_STORAGE_KEY")
    parser.add_argument("--storage-bucket", default="sources")
    args = parser.parse_args()
    try:
        if args.action == "restore":
            _require(
                args.artifact.stat().st_size <= MAX_ARTIFACT_BYTES * 2,
                "Artifact file exceeds size limit",
            )
            artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
            result = restore_plan(artifact, args.owner)
        else:
            _require(args.source_workspace is not None, "--source-workspace is required")
            result = {
                "source_workspace_id": str(args.source_workspace),
                "owner_id": str(args.owner),
                "execute": False,
            }
        if args.execute:
            database_url = _env(args.database_url_env)
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            engine = create_async_engine(database_url, hide_parameters=True)
            driver = GraphDatabase.driver(
                _env(args.neo4j_url_env),
                auth=(_env(args.neo4j_user_env), _env(args.neo4j_password_env)),
            )
            storage = Storage(
                _env(args.storage_url_env), args.storage_bucket, _env(args.storage_key_env)
            )
            try:

                async def run() -> dict[str, Any]:
                    try:
                        async with AsyncSession(engine) as db:
                            with driver.session() as graph:
                                if args.action == "export":
                                    exported = await export_snapshot(
                                        db, graph, storage, args.source_workspace, args.owner
                                    )
                                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                    descriptor = os.open(args.artifact, flags, 0o600)
                                    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                                        output.write(
                                            json.dumps(exported, ensure_ascii=False, indent=2)
                                            + "\n"
                                        )
                                    return {
                                        "artifact": str(args.artifact),
                                        "sha256": exported["sha256"],
                                        "sources": len(exported["payload"]["sources"]),
                                        "execute": True,
                                    }
                                return await restore_snapshot(
                                    db, graph, storage, artifact, args.owner
                                )
                    finally:
                        await engine.dispose()

                result = asyncio.run(run())
            finally:
                storage.close()
                driver.close()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc) if isinstance(exc, SnapshotError) else type(exc).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

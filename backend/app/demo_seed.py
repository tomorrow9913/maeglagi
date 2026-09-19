"""Explicit, idempotent import of the public PoC text fixture into one workspace.

Dry run is the default. This module never imports private workspace data or creates
recording objects, embeddings, credentials, or provider requests.
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.modules.context_engine.application.entity_resolution import entity_id, normalize_name
from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

FIXTURE = Path(__file__).with_name("demo_data") / "poc.json"
GRAPH_KINDS = {
    "person": "Person",
    "project": "Project",
    "decision": "Decision",
    "task": "Task",
    "event": "Event",
}
GRAPH_RELATIONS = {
    "participates_in": "PARTICIPATED_IN",
    "decided": "DECIDED_IN",
    "assigned_to": "ASSIGNED_TO",
    "relates_to": "RELATED_TO",
}


class SeedError(RuntimeError):
    pass


def fixture_id(workspace_id: UUID, kind: str, key: str) -> UUID:
    return uuid5(workspace_id, f"maeglagi-public-poc:{kind}:{key}")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_fixture() -> tuple[dict[str, Any], str]:
    raw = FIXTURE.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or len(data.get("workspaces", [])) != 1:
        raise SeedError("Expected one public PoC workspace in the fixture")
    return data, hashlib.sha256(raw).hexdigest()


@dataclass
class SeedPlan:
    workspace: Workspace
    marker: dict[str, str]
    people: list[WorkspacePerson]
    projects: list[WorkspaceProject]
    membership: list[ProjectMember]
    sources: list[Source]
    source_projects: list[SourceProject]
    source_people: list[SourcePerson]
    chunks: list[Chunk]
    contexts: list[ContextRecord]
    context_store: ContextStoreRecord
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]

    def counts(self) -> dict[str, int]:
        return {
            "people": len(self.people),
            "projects": len(self.projects),
            "membership": len(self.membership),
            "sources": len(self.sources),
            "source_projects": len(self.source_projects),
            "source_people": len(self.source_people),
            "chunks": len(self.chunks),
            "contexts": len(self.contexts),
            "context_store": 1,
            "graph_nodes": len(self.graph_nodes),
            "graph_edges": len(self.graph_edges),
        }


def build_plan(
    owner_id: UUID, workspace_id: UUID, fixture: dict[str, Any], digest: str
) -> SeedPlan:
    marker = {"dataset": "public-poc-v1", "sha256": digest}
    workspace_fixture = fixture["workspaces"][0]
    workspace = Workspace(
        id=workspace_id,
        owner_id=owner_id,
        name=workspace_fixture["name"],
        created_at=_time(workspace_fixture["createdAt"]),
        model_settings={"demo_seed": marker},
    )
    node_rows = fixture["knowledgeGraph"]["nodes"]
    person_rows = [node for node in node_rows if node["type"] == "person"]
    project_rows = [node for node in node_rows if node["type"] == "project"]
    people = [
        WorkspacePerson(
            id=fixture_id(workspace_id, "person", row["id"]),
            workspace_id=workspace_id,
            owner_id=owner_id,
            name=row["label"],
            email=None,
            email_normalized=None,
            created_at=workspace.created_at,
            updated_at=workspace.created_at,
        )
        for row in person_rows
    ]
    projects = [
        WorkspaceProject(
            id=fixture_id(workspace_id, "project", row["id"]),
            workspace_id=workspace_id,
            owner_id=owner_id,
            name=row["label"],
            created_at=workspace.created_at,
            updated_at=workspace.created_at,
        )
        for row in project_rows
    ]
    person_by_name = {person.name: person for person in people}
    project_id = projects[0].id if len(projects) == 1 else None
    membership = [
        ProjectMember(
            id=fixture_id(workspace_id, "member", f"{project.id}:{person.id}"),
            workspace_id=workspace_id,
            project_id=project.id,
            person_id=person.id,
        )
        for project in projects
        for person in people
    ]
    content_by_source = {item["sourceId"]: item for item in fixture["sourceContents"]}
    source_by_key: dict[str, Source] = {}
    source_people: list[SourcePerson] = []
    sources: list[Source] = []
    chunks: list[Chunk] = []
    source_projects: list[SourceProject] = []
    chunk_by_key: dict[str, Chunk] = {}
    for row in fixture["sources"]:
        key = row["id"]
        content = content_by_source[key]
        text = "\n\n".join(item["text"] for item in content["chunks"])
        participants: dict[UUID, WorkspacePerson] = {}
        utterances: list[dict[str, Any]] = []
        for item in content["chunks"]:
            if row["kind"] != "meeting":
                continue
            speaker, sep, spoken = item["text"].partition(": ")
            person = person_by_name.get(speaker) if sep else None
            if person is not None:
                participants[person.id] = person
            utterances.append(
                {
                    "id": item["id"],
                    "personId": str(person.id) if person else None,
                    "speakerName": speaker if sep else "발언자",
                    "text": spoken if sep else item["text"],
                    "startSeconds": item.get("startSeconds"),
                    "endSeconds": item.get("endSeconds"),
                }
            )
        project_snapshot = [
            {
                "id": str(project.id),
                "name": project.name,
                "goal": None,
                "description": None,
                "ownerPersonId": None,
                "ownerName": None,
                "ownerRole": None,
                "startsOn": None,
                "endsOn": None,
            }
            for project in projects
        ]
        snapshot = {
            "project": project_snapshot[0] if project_snapshot else None,
            "projects": project_snapshot,
            "people": [
                {
                    "id": str(person.id),
                    "name": person.name,
                    "role": None,
                    "email": None,
                    "aliases": [],
                }
                for person in participants.values()
            ],
        }
        source = Source(
            id=fixture_id(workspace_id, "source", key),
            workspace_id=workspace_id,
            owner_id=owner_id,
            kind=row["kind"],
            title=row["title"],
            object_path=f"public-demo-text/{workspace_id}/{key}",
            # No binary fixture exists, including for meetings named as recordings.
            content_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            duration_seconds=row.get("durationSeconds"),
            transcript_text=text if row["kind"] == "meeting" else None,
            raw_transcript_text=text if row["kind"] == "meeting" else None,
            raw_utterances=utterances,
            review_utterances=utterances,
            review_state=ReviewState.CONFIRMED if row["kind"] == "meeting" else None,
            confirmed_at=_time(row["createdAt"]) if row["kind"] == "meeting" else None,
            confirmed_snapshot=snapshot if row["kind"] == "meeting" else None,
            content_text=text,
            status=SourceStatus.SUCCEEDED,
            processing_stage=ProcessingStage.COMPLETED,
            progress=1,
            project_id=project_id,
            created_at=_time(row["createdAt"]),
        )
        sources.append(source)
        source_by_key[key] = source
        if project_id:
            source_projects.append(
                SourceProject(
                    id=fixture_id(workspace_id, "source-project", key),
                    workspace_id=workspace_id,
                    source_id=source.id,
                    project_id=project_id,
                )
            )
        for person in participants.values():
            source_people.append(
                SourcePerson(
                    id=fixture_id(workspace_id, "source-person", f"{key}:{person.id}"),
                    workspace_id=workspace_id,
                    source_id=source.id,
                    person_id=person.id,
                    role="participant",
                )
            )
        for position, item in enumerate(content["chunks"]):
            chunk = Chunk(
                id=fixture_id(workspace_id, "chunk", item["id"]),
                workspace_id=workspace_id,
                source_id=source.id,
                owner_id=owner_id,
                position=position,
                content=item["text"],
                start_seconds=item.get("startSeconds"),
                end_seconds=item.get("endSeconds"),
                embedding=None,
                created_at=source.created_at,
            )
            chunks.append(chunk)
            chunk_by_key[item["id"]] = chunk
    contexts: list[ContextRecord] = []
    supersedes = {
        row["supersededBy"]: row["id"] for row in fixture["contextItems"] if row.get("supersededBy")
    }
    for row in fixture["contextItems"]:
        evidence = row["sources"][0]
        contexts.append(
            ContextRecord(
                id=fixture_id(workspace_id, "context", row["id"]),
                workspace_id=workspace_id,
                owner_id=owner_id,
                source_id=source_by_key[evidence["id"]].id,
                chunk_id=chunk_by_key[evidence["chunkId"]].id,
                kind=row["kind"],
                title=row["title"],
                body=row["summary"],
                occurred_at=_time(row["occurredAt"]),
                metadata_={
                    "key": row["id"],
                    **({"supersedes": supersedes[row["id"]]} if row["id"] in supersedes else {}),
                },
                created_at=_time(row["occurredAt"]),
            )
        )
    state = fixture["contextStore"]
    store = ContextStoreRecord(
        id=fixture_id(workspace_id, "context-store", "current"),
        workspace_id=workspace_id,
        owner_id=owner_id,
        subject=state["subject"],
        summary=state["summary"],
        current_state=state["currentState"],
        open_issues=[_store_item(item, source_by_key) for item in state["openIssues"]],
        decisions=[_store_item(item, source_by_key) for item in state["decisions"]],
        next_actions=[_store_item(item, source_by_key) for item in state["nextActions"]],
        source_ids=[str(source_by_key[key].id) for key in state["sourceIds"]],
        updated_at=_time(state["updatedAt"]),
    )
    graph_nodes, graph_edges = _graph_rows(
        fixture, workspace_id, source_by_key, chunk_by_key, people, projects
    )
    return SeedPlan(
        workspace,
        marker,
        people,
        projects,
        membership,
        sources,
        source_projects,
        source_people,
        chunks,
        contexts,
        store,
        graph_nodes,
        graph_edges,
    )


def _store_item(item: dict[str, Any], sources: dict[str, Source]) -> dict[str, Any]:
    return {
        "title": item["title"],
        "description": item["description"],
        "source_refs": item["sourceRefs"],
        "source_id": str(sources[item["sourceId"]].id) if item.get("sourceId") else None,
        **({"decided_at": item.get("decidedAt")} if item.get("decidedAt") else {}),
        **({"assignee": item.get("assignee")} if item.get("assignee") else {}),
        **({"due_at": item.get("dueAt")} if item.get("dueAt") else {}),
    }


def _graph_rows(
    fixture: dict[str, Any],
    workspace_id: UUID,
    sources: dict[str, Source],
    chunks: dict[str, Chunk],
    people: list[WorkspacePerson],
    projects: list[WorkspaceProject],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    people_by_name = {item.name: item for item in people}
    projects_by_name = {item.name: item for item in projects}
    ids: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for node in fixture["knowledgeGraph"]["nodes"]:
        kind = GRAPH_KINDS[node["type"]]
        directory = (people_by_name if kind == "Person" else projects_by_name).get(node["label"])
        identifier = f"directory:{kind.lower()}:{directory.id}" if directory is not None else None
        node_id = (
            entity_id(workspace_id, kind, f"id:{identifier}")
            if identifier
            else (fixture_id(workspace_id, "graph-node", node["id"]))
        )
        ids[node["id"]] = str(node_id)
        evidence = node["sources"][0]
        rows.append(
            {
                "id": str(node_id),
                "workspace_id": str(workspace_id),
                "kind": kind,
                "name": node["label"],
                "aliases": [],
                "keys": [normalize_name(node["label"], kind)],
                "identifiers": [identifier] if identifier else [],
                "source_ids": [str(sources[item["id"]].id) for item in node["sources"]],
                "source_id": str(sources[evidence["id"]].id),
                "chunk_id": str(chunks[evidence["chunkId"]].id),
                "timestamp": None,
                "superseded_by": None,
            }
        )
    edges: list[dict[str, Any]] = []
    for edge in fixture["knowledgeGraph"]["edges"]:
        if edge["type"] == "supersedes":
            old = next(row for row in rows if row["id"] == ids[edge["target"]])
            old["superseded_by"] = ids[edge["source"]]
            continue
        edges.append(
            {
                "id": str(fixture_id(workspace_id, "graph-edge", edge["id"])),
                "workspace_id": str(workspace_id),
                "source": ids[edge["source"]],
                "target": ids[edge["target"]],
                "kind": GRAPH_RELATIONS[edge["type"]],
                "valid_from": _time(edge["validFrom"] + "T00:00:00Z").isoformat()
                if edge.get("validFrom")
                else None,
                "valid_to": _time(edge["validTo"] + "T23:59:59Z").isoformat()
                if edge.get("validTo")
                else None,
            }
        )
    return rows, edges


async def _ensure(
    session: AsyncSession, model: type[SQLModel], row: SQLModel, workspace_id: UUID
) -> bool:
    existing = await session.get(model, row.id)
    if existing is not None:
        if getattr(existing, "workspace_id", workspace_id) != workspace_id:
            raise SeedError(f"Deterministic ID collision in {model.__name__}")
        return False
    session.add(row)
    return True


async def seed_postgres(session: AsyncSession, plan: SeedPlan) -> dict[str, int]:
    existing = await session.get(Workspace, plan.workspace.id, with_for_update=True)
    if existing is not None:
        if (
            existing.owner_id != plan.workspace.owner_id
            or (existing.model_settings or {}).get("demo_seed") != plan.marker
        ):
            raise SeedError("Workspace exists and is not this exact public PoC seed")
    else:
        session.add(plan.workspace)
        await session.flush()
    # A marked workspace may have been partially seeded before a prior failure.
    found = await session.exec(
        select(ContextStoreRecord).where(ContextStoreRecord.workspace_id == plan.workspace.id)
    )
    if any(row.id != plan.context_store.id for row in found.all()):
        raise SeedError("Workspace already has an unrelated context store")
    order: list[tuple[str, type[SQLModel], list[SQLModel]]] = [
        ("people", WorkspacePerson, plan.people),
        ("projects", WorkspaceProject, plan.projects),
        ("membership", ProjectMember, plan.membership),
        ("sources", Source, plan.sources),
        ("source_projects", SourceProject, plan.source_projects),
        ("source_people", SourcePerson, plan.source_people),
        ("chunks", Chunk, plan.chunks),
        ("contexts", ContextRecord, plan.contexts),
        ("context_store", ContextStoreRecord, [plan.context_store]),
    ]
    added: dict[str, int] = {}
    for name, model, rows in order:
        added[name] = sum([await _ensure(session, model, row, plan.workspace.id) for row in rows])
        await session.flush()
    await session.commit()
    return added


async def seed_graph(plan: SeedPlan) -> None:
    from app.core.config import get_settings
    from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

    if not get_settings().neo4j_enabled:
        return
    store = Neo4jGraphStore.from_settings()
    try:
        await store.verify_connectivity()
        collisions = await store.execute(
            """
        UNWIND $ids AS id
        MATCH (n:Entity {id: id})
        WHERE n.workspace_id <> $workspace_id
        RETURN n.id AS id
        """,
            {
                "ids": [node["id"] for node in plan.graph_nodes],
                "workspace_id": str(plan.workspace.id),
            },
        )
        if collisions:
            raise SeedError("Graph entity ID belongs to another workspace")
        await store.execute(
            """
        UNWIND $rows AS row
        MERGE (n:Entity {id: row.id})
        ON CREATE SET n.workspace_id = row.workspace_id, n.kind = row.kind, n.name = row.name,
            n.aliases = row.aliases, n.keys = row.keys, n.identifiers = row.identifiers,
            n.source_ids = row.source_ids, n.source_id = row.source_id,
            n.chunk_id = row.chunk_id, n.timestamp = row.timestamp,
            n.superseded_by = row.superseded_by
        """,
            {"rows": plan.graph_nodes},
        )
        for kind in sorted(GRAPH_RELATIONS.values()):
            rows = [row for row in plan.graph_edges if row["kind"] == kind]
            if not rows:
                continue
            # Relationship type is drawn only from the hard-coded allowlist above.
            await store.execute(
                f"""
            UNWIND $rows AS row
            MATCH (a:Entity {{id: row.source, workspace_id: row.workspace_id}})
            MATCH (b:Entity {{id: row.target, workspace_id: row.workspace_id}})
            MERGE (a)-[r:{kind} {{id: row.id}}]->(b)
            ON CREATE SET r.workspace_id = row.workspace_id,
                r.valid_from = CASE WHEN row.valid_from IS NULL THEN null
                                    ELSE datetime(row.valid_from) END,
                r.valid_to = CASE WHEN row.valid_to IS NULL THEN null
                                  ELSE datetime(row.valid_to) END
            """,
                {"rows": rows},
            )
    finally:
        await store.close()


async def execute(plan: SeedPlan) -> dict[str, int]:
    from app.core.database import session_factory

    async with session_factory() as session:
        try:
            added = await seed_postgres(session, plan)
        except BaseException:
            await session.rollback()
            raise
    await seed_graph(plan)
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the public PoC text fixture")
    parser.add_argument("--owner", type=UUID, required=True, help="Dedicated public owner UUID")
    parser.add_argument(
        "--workspace", type=UUID, required=True, help="Dedicated public workspace UUID"
    )
    parser.add_argument("--execute", action="store_true", help="Write to configured databases")
    args = parser.parse_args()
    fixture, digest = load_fixture()
    plan = build_plan(args.owner, args.workspace, fixture, digest)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "workspace": str(args.workspace),
                    "owner": str(args.owner),
                    "fixture_sha256": digest,
                    "counts": plan.counts(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    added = asyncio.run(execute(plan))
    print(
        json.dumps(
            {"mode": "executed", "workspace": str(args.workspace), "added": added},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

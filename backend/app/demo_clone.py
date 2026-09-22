"""Clone the configured, normalized public text demo into a user's workspace."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import inspect, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.demo_snapshot import _remap_directory_identifier
from app.modules.context_engine.domain.ontology import RelationKind
from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
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


class CloneUnavailable(Exception):
    """The published data cannot be copied completely and safely."""


def target_id(owner_id: UUID, public_id: UUID) -> UUID:
    return uuid5(owner_id, f"public-demo-clone-v1:{public_id}")


def mapped(value: UUID | str | None, target: UUID) -> UUID | None:
    return uuid5(target, str(value)) if value is not None else None


def copy_row(row: object, **changes: object) -> object:
    values = {
        attr.key: deepcopy(getattr(row, attr.key)) for attr in inspect(type(row)).column_attrs
    }
    values.update(changes)
    return type(row)(**values)


def remap_snapshot(snapshot: dict | None, target: UUID) -> dict | None:
    if snapshot is None:
        return None
    result = deepcopy(snapshot)
    for key in ("project",):
        if result.get(key):
            result[key]["id"] = str(mapped(result[key]["id"], target))
            if result[key].get("ownerPersonId"):
                result[key]["ownerPersonId"] = str(mapped(result[key]["ownerPersonId"], target))
    for key in ("projects", "people", "roster"):
        for item in result.get(key, []):
            item["id"] = str(mapped(item["id"], target))
            if item.get("ownerPersonId"):
                item["ownerPersonId"] = str(mapped(item["ownerPersonId"], target))
    return result


def remap_utterances(items: list[dict], target: UUID) -> list[dict]:
    result = deepcopy(items)
    for item in result:
        if item.get("personId"):
            item["personId"] = str(mapped(item["personId"], target))
    return result


async def _rows(db: AsyncSession, model: type, workspace_id: UUID) -> list:
    return list((await db.exec(select(model).where(model.workspace_id == workspace_id))).all())


async def _graph_rows(graph: Neo4jGraphStore, workspace_id: UUID) -> tuple[list[dict], list[dict]]:
    nodes = await graph.execute(
        "MATCH (n:Entity {workspace_id: $workspace}) RETURN properties(n) AS props",
        {"workspace": str(workspace_id)},
    )
    edges = await graph.execute(
        "MATCH (a:Entity {workspace_id: $workspace})-[r]->"
        "(b:Entity {workspace_id: $workspace}) "
        "RETURN a.id AS source, b.id AS target, type(r) AS kind, properties(r) AS props",
        {"workspace": str(workspace_id)},
    )
    return [dict(row["props"]) for row in nodes], [
        {
            **dict(row["props"]),
            "source": row["source"],
            "target": row["target"],
            "kind": row["kind"],
        }
        for row in edges
    ]


def _graph_nodes(nodes: list[dict], target: UUID) -> list[dict]:
    result = []
    for original in nodes:
        row = deepcopy(original)
        row.update(
            id=str(mapped(original["id"], target)),
            workspace_id=str(target),
            source_id=str(mapped(original["source_id"], target)),
            source_ids=[str(mapped(item, target)) for item in original.get("source_ids", [])],
            chunk_id=str(mapped(original["chunk_id"], target))
            if original.get("chunk_id")
            else None,
            superseded_by=str(mapped(original["superseded_by"], target))
            if original.get("superseded_by")
            else None,
            identifiers=[
                _remap_directory_identifier(item, target)
                for item in original.get("identifiers", [])
            ],
        )
        result.append({key: value for key, value in row.items() if value is not None})
    return result


def _graph_edges(edges: list[dict], target: UUID) -> list[dict]:
    result = []
    allowed = {kind.value for kind in RelationKind}
    for original in edges:
        if original["kind"] not in allowed:
            raise CloneUnavailable("Unsupported demo graph relation")
        row = deepcopy(original)
        row.update(
            id=str(mapped(original["id"], target)),
            workspace_id=str(target),
            source=str(mapped(original["source"], target)),
            target=str(mapped(original["target"], target)),
            source_id=str(mapped(original["source_id"], target))
            if original.get("source_id")
            else None,
            chunk_id=str(mapped(original["chunk_id"], target))
            if original.get("chunk_id")
            else None,
        )
        result.append(row)
    return result


async def _write_graph(
    graph: Neo4jGraphStore, target: UUID, nodes: list[dict], edges: list[dict]
) -> None:
    async with graph._driver.session() as connection, await connection.begin_transaction() as tx:
        existing = await tx.run(
            "MATCH (n:Entity {workspace_id: $workspace}) RETURN count(n) AS count",
            workspace=str(target),
        )
        if (await existing.single())["count"]:
            raise CloneUnavailable("Target graph already exists")
        for row in nodes:
            await tx.run(
                "CREATE (n:Entity {id: $id, workspace_id: $workspace}) SET n += $props",
                id=row["id"],
                workspace=str(target),
                props=row,
            )
        for row in edges:
            kind = row["kind"]  # fixed RelationKind allowlist
            props = {
                key: value
                for key, value in row.items()
                if key not in {"source", "target", "kind", "valid_from", "valid_to"}
                and value is not None
            }
            await tx.run(
                f"MATCH (a:Entity {{id: $source, workspace_id: $workspace}}), "
                f"(b:Entity {{id: $target, workspace_id: $workspace}}) "
                f"CREATE (a)-[r:{kind}]->(b) SET r += $props "
                "SET r.valid_from = CASE WHEN $valid_from IS NULL THEN null "
                "ELSE datetime($valid_from) END, "
                "r.valid_to = CASE WHEN $valid_to IS NULL THEN null "
                "ELSE datetime($valid_to) END",
                source=row["source"],
                target=row["target"],
                workspace=str(target),
                props=props,
                valid_from=str(row["valid_from"]) if row.get("valid_from") else None,
                valid_to=str(row["valid_to"]) if row.get("valid_to") else None,
            )
        await tx.commit()


async def _delete_graph(graph: Neo4jGraphStore, target: UUID) -> None:
    await graph.execute(
        "MATCH (n:Entity {workspace_id: $workspace}) DETACH DELETE n", {"workspace": str(target)}
    )


async def clone_demo(
    db: AsyncSession, graph: Neo4jGraphStore | None, public: Workspace, owner_id: UUID
) -> tuple[Workspace, int]:
    """Return an existing private clone unchanged, or copy the published state once."""
    target = target_id(owner_id, public.id)
    # A transaction-scoped lock serializes retries even before the target row exists.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(target)}
    )
    existing = await db.get(Workspace, target)
    if existing is not None:
        if existing.owner_id != owner_id:
            raise CloneUnavailable("Clone workspace owner mismatch")
        return existing, len(await _rows(db, Source, target))
    try:
        people = await _rows(db, WorkspacePerson, public.id)
        projects = await _rows(db, WorkspaceProject, public.id)
        members = await _rows(db, ProjectMember, public.id)
        sources = await _rows(db, Source, public.id)
        source_projects = await _rows(db, SourceProject, public.id)
        source_people = await _rows(db, SourcePerson, public.id)
        chunks = await _rows(db, Chunk, public.id)
        contexts = await _rows(db, ContextRecord, public.id)
        stores = await _rows(db, ContextStoreRecord, public.id)
        if graph is not None:
            await graph.verify_connectivity()
            nodes, edges = await _graph_rows(graph, public.id)
        else:
            nodes, edges = [], []
    except Exception as exc:
        raise CloneUnavailable("Public demo data is unavailable") from exc
    copy_graph = bool(nodes or edges)
    if (
        len(sources) != 3
        or len(chunks) != 7
        or len(contexts) != 6
        or len(stores) != 1
        or len(people) != 2
        or len(projects) != 1
        or (copy_graph and (len(nodes) != 7 or len(edges) != 8))
        or not any(source.kind == "meeting" for source in sources)
        or not (public.model_settings or {}).get("demo_seed")
    ):
        raise CloneUnavailable("Public demo is incomplete")
    if any(
        row.owner_id != public.owner_id
        for rows in (people, projects, sources, chunks, contexts, stores)
        for row in rows
    ):
        raise CloneUnavailable("Public demo ownership is inconsistent")
    if any(
        source.content_type != "text/plain"
        or not source.object_path.startswith("public-demo-text/")
        or not source.content_text
        or source.status != SourceStatus.SUCCEEDED
        or source.processing_stage != ProcessingStage.COMPLETED
        for source in sources
    ):
        raise CloneUnavailable("Only normalized text demo sources can be cloned")
    source_ids = {str(source.id) for source in sources}
    chunk_ids = {str(chunk.id) for chunk in chunks}
    if (
        any(str(chunk.source_id) not in source_ids for chunk in chunks)
        or any(
            str(context.source_id) not in source_ids
            or (context.chunk_id and str(context.chunk_id) not in chunk_ids)
            for context in contexts
        )
        or any(str(item) not in source_ids for item in stores[0].source_ids)
    ):
        raise CloneUnavailable("Public demo has dangling evidence references")
    if any(
        str(node.get("source_id")) not in source_ids
        or any(str(item) not in source_ids for item in node.get("source_ids", []))
        or (node.get("chunk_id") and str(node["chunk_id"]) not in chunk_ids)
        for node in nodes
    ):
        raise CloneUnavailable("Public demo graph has dangling evidence references")
    node_ids = {str(node["id"]) for node in nodes}
    if any(
        (node.get("superseded_by") and str(node["superseded_by"]) not in node_ids) for node in nodes
    ) or any(
        str(edge["source"]) not in node_ids or str(edge["target"]) not in node_ids for edge in edges
    ):
        raise CloneUnavailable("Public demo graph has dangling entity references")
    graph_nodes, graph_edges = _graph_nodes(nodes, target), _graph_edges(edges, target)
    first = min(
        (source for source in sources if source.kind == "meeting"), key=lambda item: item.created_at
    )
    draft_id = mapped("editing-draft", target)
    draft = copy_row(
        first,
        id=draft_id,
        workspace_id=target,
        owner_id=owner_id,
        title=f"{first.title} · 편집 체험용 초안",
        object_path=f"public-demo-text/{target}/{draft_id}",
        project_id=mapped(first.project_id, target),
        raw_utterances=remap_utterances(first.raw_utterances, target),
        review_utterances=remap_utterances(first.review_utterances, target),
        review_state=ReviewState.AWAITING_REVIEW,
        review_revision=0,
        confirmed_at=None,
        confirmed_snapshot=None,
        analysis_checkpoint=None,
        status=SourceStatus.AWAITING_REVIEW,
        processing_stage=ProcessingStage.AWAITING_REVIEW,
        progress=0,
        created_at=datetime.now(UTC),
    )
    cloned = Workspace(
        id=target, owner_id=owner_id, name=f"{public.name[:105]} · 내 사본", model_settings={}
    )
    graph_written = False
    try:
        db.add(cloned)
        await db.flush()
        for person in people:
            db.add(
                copy_row(
                    person, id=mapped(person.id, target), workspace_id=target, owner_id=owner_id
                )
            )
        await db.flush()
        for project in projects:
            db.add(
                copy_row(
                    project,
                    id=mapped(project.id, target),
                    workspace_id=target,
                    owner_id=owner_id,
                    owner_person_id=mapped(project.owner_person_id, target),
                )
            )
        await db.flush()
        for member in members:
            db.add(
                copy_row(
                    member,
                    id=mapped(member.id, target),
                    workspace_id=target,
                    project_id=mapped(member.project_id, target),
                    person_id=mapped(member.person_id, target),
                )
            )
        for source in sources:
            db.add(
                copy_row(
                    source,
                    id=mapped(source.id, target),
                    workspace_id=target,
                    owner_id=owner_id,
                    object_path=f"public-demo-text/{target}/{mapped(source.id, target)}",
                    project_id=mapped(source.project_id, target),
                    raw_utterances=remap_utterances(source.raw_utterances, target),
                    review_utterances=remap_utterances(source.review_utterances, target),
                    confirmed_snapshot=remap_snapshot(source.confirmed_snapshot, target),
                    analysis_checkpoint=None,
                )
            )
        db.add(draft)
        await db.flush()
        for row in source_projects:
            db.add(
                copy_row(
                    row,
                    id=mapped(row.id, target),
                    workspace_id=target,
                    source_id=mapped(row.source_id, target),
                    project_id=mapped(row.project_id, target),
                )
            )
        for row in source_people:
            db.add(
                copy_row(
                    row,
                    id=mapped(row.id, target),
                    workspace_id=target,
                    source_id=mapped(row.source_id, target),
                    person_id=mapped(row.person_id, target),
                )
            )
        for row in source_projects:
            if row.source_id == first.id:
                db.add(
                    copy_row(
                        row,
                        id=mapped(f"draft:{row.id}", target),
                        workspace_id=target,
                        source_id=draft_id,
                        project_id=mapped(row.project_id, target),
                    )
                )
        for row in source_people:
            if row.source_id == first.id:
                db.add(
                    copy_row(
                        row,
                        id=mapped(f"draft:{row.id}", target),
                        workspace_id=target,
                        source_id=draft_id,
                        person_id=mapped(row.person_id, target),
                    )
                )
        for chunk in chunks:
            db.add(
                copy_row(
                    chunk,
                    id=mapped(chunk.id, target),
                    workspace_id=target,
                    owner_id=owner_id,
                    source_id=mapped(chunk.source_id, target),
                )
            )
        await db.flush()
        for context in contexts:
            db.add(
                copy_row(
                    context,
                    id=mapped(context.id, target),
                    workspace_id=target,
                    owner_id=owner_id,
                    source_id=mapped(context.source_id, target),
                    chunk_id=mapped(context.chunk_id, target),
                )
            )
        for store in stores:
            collections = {}
            for key in ("open_issues", "decisions", "next_actions"):
                collections[key] = [
                    {
                        **deepcopy(item),
                        "source_id": str(mapped(item["source_id"], target))
                        if item.get("source_id")
                        else None,
                        "source_refs": [
                            str(mapped(ref, target)) if ref in source_ids else ref
                            for ref in item.get("source_refs", [])
                        ],
                    }
                    for item in getattr(store, key)
                ]
            db.add(
                copy_row(
                    store,
                    id=mapped(store.id, target),
                    workspace_id=target,
                    owner_id=owner_id,
                    source_ids=[str(mapped(item, target)) for item in store.source_ids],
                    **collections,
                )
            )
        await db.flush()
        if copy_graph:
            await _write_graph(graph, target, graph_nodes, graph_edges)
            graph_written = True
        await db.commit()
    except Exception:
        await db.rollback()
        if graph_written:
            # A commit error may be ambiguous. Never delete a graph belonging to a committed clone.
            from sqlalchemy.ext.asyncio import AsyncSession as VerifySession

            try:
                async with VerifySession(bind=db.bind) as verify:
                    committed = await verify.get(Workspace, target)
            except Exception:
                committed = True
            if committed is None:
                await _delete_graph(graph, target)
        raise
    return cloned, len(sources) + 1

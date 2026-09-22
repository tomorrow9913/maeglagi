"""Focused regression checks for agent workflow review findings."""

from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.service import AgentWorkflowService
from app.modules.agent_workflows.validation import validate_extraction
from app.modules.context_engine.application.context_store import merge_extraction
from app.modules.context_engine.application.entity_resolution import entity_id
from app.modules.context_engine.domain.context_store import ContextStoreState
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    WorkspacePerson,
    WorkspaceProject,
)
from tests.test_agent_workflows import database as original_database
from tests.test_agent_workflows import extraction
from tests.test_entity_resolution import FakeStore


@pytest.fixture
async def database():
    async for factory in original_database.__wrapped__():
        yield factory


def test_person_honorific_relation_endpoint_is_valid() -> None:
    text = "민수님은 캐시를 도입합니다."
    proposal = extraction(text)
    proposal["relations"][0]["source"] = "민수님"
    source = Source(
        owner_id=uuid4(),
        workspace_id=uuid4(),
        kind="document",
        title="Notes",
        object_path="inline:test",
        content_type="text/plain",
        size_bytes=len(text.encode()),
    )

    validated = validate_extraction(proposal, source=source, text=text, known_decisions=[])

    assert validated.relations[0].source == "민수님"


def test_decision_context_is_promoted_to_decision_event() -> None:
    text = "감사 이벤트에는 비밀값을 저장하지 않는다."
    proposal = extraction(text)
    proposal["events"] = []
    proposal["relations"] = []
    proposal["contexts"] = [
        {
            "kind": "decision",
            "title": "감사 이벤트에서 비밀값 제외",
            "body": text,
            "occurred_at": "2026-09-22",
            "source_refs": [text],
        }
    ]
    source = Source(
        owner_id=uuid4(),
        workspace_id=uuid4(),
        kind="document",
        title="Audit policy",
        object_path="inline:test",
        content_type="text/plain",
        size_bytes=len(text.encode()),
    )

    validated = validate_extraction(proposal, source=source, text=text, known_decisions=[])

    assert len(validated.events) == 1
    assert validated.events[0].kind.value == "Decision"
    assert validated.events[0].name == "감사 이벤트에서 비밀값 제외"
    assert validated.events[0].source_refs == [text]
    state = merge_extraction(ContextStoreState(subject="Audit policy"), validated, source.id)
    assert [decision.title for decision in state.decisions] == ["감사 이벤트에서 비밀값 제외"]


def test_existing_decision_event_is_not_duplicated_by_context() -> None:
    text = "캐시를 도입한다."
    proposal = extraction(text, decision="캐시 도입")
    proposal["contexts"] = [
        {
            "kind": "decision",
            "title": "캐시 도입",
            "body": text,
            "occurred_at": None,
            "source_refs": [text],
        }
    ]
    source = Source(
        owner_id=uuid4(),
        workspace_id=uuid4(),
        kind="document",
        title="Cache decision",
        object_path="inline:test",
        content_type="text/plain",
        size_bytes=len(text.encode()),
    )

    validated = validate_extraction(proposal, source=source, text=text, known_decisions=[])

    assert [event.name for event in validated.events] == ["캐시 도입"]


def test_ambiguous_honorific_relation_endpoint_is_rejected() -> None:
    text = "민수님은 캐시를 도입합니다."
    proposal = extraction(text)
    proposal["relations"][0]["source"] = "민수님"
    proposal["entities"].append(
        {
            "name": "민수님",
            "kind": "Person",
            "aliases": [],
            "identifiers": [],
            "source_refs": [text],
        }
    )
    source = Source(
        owner_id=uuid4(),
        workspace_id=uuid4(),
        kind="document",
        title="Notes",
        object_path="inline:test",
        content_type="text/plain",
        size_bytes=len(text.encode()),
    )

    with pytest.raises(WorkflowError) as exc:
        validate_extraction(proposal, source=source, text=text, known_decisions=[])

    assert exc.value.code == "invalid_relation"


@pytest.mark.asyncio
async def test_document_directory_is_bound_to_fingerprint_and_graph(database, monkeypatch) -> None:
    from app.modules.agent_workflows import service as workflow_module

    graph = FakeStore()

    async def close_graph() -> None:
        pass

    graph.close = close_graph
    monkeypatch.setattr(workflow_module.Neo4jGraphStore, "from_settings", lambda _settings: graph)
    settings = get_settings().model_copy(
        update={
            "neo4j_uri": "bolt://fake",
            "neo4j_username": "fake",
            "neo4j_password": SecretStr("fake"),
        }
    )
    owner = uuid4()
    text = "민수와 Search는 캐시를 도입합니다."
    async with database() as session:
        workflow = AgentWorkflowService(session, settings)
        workspace = await workflow.create_workspace(owner_id=owner, name="Keyless")
        person = WorkspacePerson(owner_id=owner, workspace_id=workspace.id, name="민수")
        session.add(person)
        await session.flush()
        project = WorkspaceProject(owner_id=owner, workspace_id=workspace.id, name="Search")
        session.add(project)
        await session.flush()
        session.add(
            ProjectMember(
                workspace_id=workspace.id,
                project_id=project.id,
                person_id=person.id,
            )
        )
        await session.commit()
        source = await workflow.create_text_source(
            owner_id=owner,
            workspace_id=workspace.id,
            title="Notes",
            text=text,
            project_ids=[project.id],
        )
        before = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=source.id
        )
        assert before.directory["roster"][0]["id"] == str(person.id)
        person.role = "Lead"
        session.add(person)
        await session.commit()
        proposal = extraction(text)
        proposal["entities"].append(
            {
                "name": "Search",
                "kind": "Project",
                "aliases": [],
                "identifiers": [],
                "source_refs": [text],
            }
        )
        with pytest.raises(WorkflowError) as exc:
            await workflow.submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=source.id,
                expected_revision=0,
                expected_fingerprint=before.fingerprint,
                result=proposal,
            )
        assert exc.value.code == "stale_context"
        fresh = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=source.id
        )
        assert fresh.fingerprint != before.fingerprint
        await workflow.submit_analysis(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=source.id,
            expected_revision=0,
            expected_fingerprint=fresh.fingerprint,
            result=proposal,
        )
        graph_ids = {row["id"] for row in graph.rows("MERGE (e:Entity {id: row.id})")}
        person_id = entity_id(workspace.id, "Person", f"id:directory:person:{person.id}")
        project_id = entity_id(workspace.id, "Project", f"id:directory:project:{project.id}")
        assert str(person_id) in graph_ids
        assert str(project_id) in graph_ids


async def test_direct_document_person_association_enters_directory(database):
    owner = uuid4()
    async with database() as session:
        workflow = AgentWorkflowService(session, get_settings())
        workspace = await workflow.create_workspace(owner_id=owner, name="Direct author")
        person = WorkspacePerson(owner_id=owner, workspace_id=workspace.id, name="Author")
        session.add(person)
        await session.commit()
        source = await workflow.create_text_source(
            owner_id=owner, workspace_id=workspace.id, title="Notes", text="Author wrote this."
        )
        session.add(
            SourcePerson(
                workspace_id=workspace.id, source_id=source.id, person_id=person.id, role="author"
            )
        )
        await session.commit()
        context = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=source.id
        )
        assert [row["id"] for row in context.directory["people"]] == [str(person.id)]


async def test_directory_order_is_independent_of_database_row_order():
    from types import SimpleNamespace

    from app.modules.agent_workflows.repositories import WorkflowRepository

    owner, workspace = uuid4(), uuid4()
    people = [
        WorkspacePerson(owner_id=owner, workspace_id=workspace, name=name)
        for name in ("One", "Two")
    ]
    project = WorkspaceProject(owner_id=owner, workspace_id=workspace, name="Project")
    source = Source(
        owner_id=owner,
        workspace_id=workspace,
        kind="document",
        title="Notes",
        object_path="inline:test",
        content_type="text/plain",
        size_bytes=1,
    )

    class Session:
        def __init__(self, reverse):
            ordered = people[::-1] if reverse else people
            self.results = iter(
                [
                    [SimpleNamespace(person_id=p.id) for p in ordered],
                    [SimpleNamespace(project_id=project.id)],
                    ordered,
                    [project],
                    ordered,
                ]
            )

        async def exec(self, statement):
            rows = next(self.results)
            return SimpleNamespace(all=lambda: rows)

    first = await WorkflowRepository(Session(False)).directory_snapshot(owner, workspace, source)
    second = await WorkflowRepository(Session(True)).directory_snapshot(owner, workspace, source)
    assert first == second
    assert len(first["roster"]) == 2

"""Focused regression checks for agent workflow review findings."""

from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.service import AgentWorkflowService
from app.modules.agent_workflows.validation import validate_extraction
from app.modules.context_engine.application.entity_resolution import entity_id
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
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

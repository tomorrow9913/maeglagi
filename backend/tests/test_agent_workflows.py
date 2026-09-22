"""Keyless external analysis persists ordinary UI records without a server model."""

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.router import get_job
from app.api.workspaces import review as review_routes
from app.api.workspaces.review import ConfirmRequest, confirm_review
from app.auth.models import AuthUser
from app.core.config import get_settings
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.service import AgentWorkflowService
from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.workspaces.application import media_access
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceMember,
    WorkspacePerson,
    WorkspaceProject,
)
from tests.test_meeting_review import WORKSPACE, FakeSession


@pytest.fixture
async def database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("PG_EXECUTOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set PG_EXECUTOR_TEST_DATABASE_URL to disposable local PostgreSQL")
    if urlparse(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Agent workflow tests require loopback PostgreSQL")
    schema = f"agent_workflows_{uuid4().hex}"
    engine = create_async_engine(
        url,
        pool_size=1,
        max_overflow=0,
        connect_args={"server_settings": {"search_path": f"{schema},public,extensions"}},
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS extensions"))
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
        )
        await connection.run_sync(
            lambda sync: SQLModel.metadata.create_all(
                sync,
                checkfirst=False,
                tables=[
                    Workspace.__table__,
                    WorkspaceMember.__table__,
                    WorkspaceAuditEvent.__table__,
                    WorkspacePerson.__table__,
                    WorkspaceProject.__table__,
                    ProjectMember.__table__,
                    Source.__table__,
                    SourceProject.__table__,
                    SourcePerson.__table__,
                    Chunk.__table__,
                    ContextRecord.__table__,
                    ContextStoreRecord.__table__,
                ],
            )
        )
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def extraction(quote: str, *, kind: str = "report", decision: str = "캐시 도입") -> dict:
    return {
        "classification": {"source_type": kind, "language": "ko", "topics": ["캐시"]},
        "entities": [
            {
                "name": "민수",
                "kind": "Person",
                "aliases": [],
                "identifiers": [],
                "source_refs": [quote],
            }
        ],
        "events": [
            {
                "name": decision,
                "kind": "Decision",
                "description": "캐시를 도입한다",
                "occurred_at": None,
                "due_at": None,
                "supersedes": None,
                "source_refs": [quote],
            }
        ],
        "relations": [
            {
                "source": "민수",
                "target": decision,
                "kind": "CREATED",
                "valid_from": None,
                "valid_to": None,
                "source_refs": [quote],
            }
        ],
        "contexts": [
            {
                "kind": "summary",
                "title": "결론",
                "body": decision,
                "occurred_at": None,
                "source_refs": [quote],
            }
        ],
        "warnings": [],
        "usage": {},
    }


def service(session: AsyncSession) -> AgentWorkflowService:
    return AgentWorkflowService(session, get_settings().model_copy(update={"neo4j_uri": ""}))


@pytest.mark.asyncio
async def test_shared_workspace_roles_keep_records_under_workspace_owner(database):
    owner, editor, viewer = uuid4(), uuid4(), uuid4()
    async with database() as session:
        workflow = service(session)
        workspace = await workflow.create_workspace(owner_id=owner, name="Shared")
        owner_membership = (
            await session.exec(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.user_id == owner,
                )
            )
        ).one()
        assert owner_membership.role == "owner"
        session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=editor,
                email="editor@example.com",
                email_normalized="editor@example.com",
                role="editor",
                invited_by=owner,
            )
        )
        session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=viewer,
                email="viewer@example.com",
                email_normalized="viewer@example.com",
                role="viewer",
                invited_by=owner,
            )
        )
        await session.commit()

        assert [row.id for row in await workflow.list_workspaces(owner_id=editor)] == [workspace.id]
        source = await workflow.create_text_source(
            owner_id=editor,
            workspace_id=workspace.id,
            title="Shared note",
            text="The editor added this.",
        )
        stored = await session.get(Source, source.id)
        assert stored is not None and stored.owner_id == owner
        assert [
            row.id
            for row in await workflow.list_sources(owner_id=viewer, workspace_id=workspace.id)
        ] == [source.id]
        assert (
            await workflow.source_content(
                owner_id=viewer, workspace_id=workspace.id, source_id=source.id
            )
        ).text == "The editor added this."
        with pytest.raises(WorkflowError, match="Workspace not found"):
            await workflow.create_text_source(
                owner_id=viewer,
                workspace_id=workspace.id,
                title="Forbidden",
                text="Viewers cannot mutate.",
            )


@pytest.mark.asyncio
async def test_stored_text_has_private_download_but_inline_text_does_not(monkeypatch):
    owner_id, workspace_id, source_id = uuid4(), uuid4(), uuid4()
    source = Source(
        id=source_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        kind="document",
        title="notes.txt",
        object_path=f"inline:{source_id}",
        content_type="text/plain",
        size_bytes=10,
    )
    settings = get_settings().model_copy(
        update={
            "supabase_url": "https://storage.example",
            "supabase_service_role_key": SecretStr("private"),
        }
    )
    with pytest.raises(media_access.MediaAccessError):
        await media_access.signed_media_url(source, settings)
    source.object_path = f"{owner_id}/{workspace_id}/{source_id}/notes.txt"

    def response(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer private"
        return httpx.Response(
            200,
            json={"signedURL": f"/object/sign/sources/{source.object_path}?token=signed"},
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        media_access.httpx,
        "AsyncClient",
        lambda *_args, **_kwargs: original_client(transport=httpx.MockTransport(response)),
    )
    signed = await media_access.signed_media_url(source, settings)
    assert signed.url.endswith("notes.txt?token=signed")
    assert "private" not in signed.url


@pytest.mark.asyncio
async def test_agent_rest_confirmation_never_enqueues_and_get_job_exposes_mode(monkeypatch):
    session = FakeSession()
    session.source.analysis_mode = "agent"
    session.source.transcript_source = "agent"
    session.source.review_utterances = [
        {"id": "u1", "speakerName": "민수", "text": "캐시를 도입합니다."}
    ]

    def forbidden(*_args, **_kwargs):
        pytest.fail("Agent confirmation must not enqueue server processing")

    monkeypatch.setattr(review_routes.process_source, "apply_async", forbidden)
    monkeypatch.setattr(review_routes, "enqueue_pg_source", forbidden)
    response = await confirm_review(
        WORKSPACE,
        session.source.id,
        ConfirmRequest(revision=0),
        AuthUser(id=session.source.owner_id),
        session,
    )
    assert response.analysis_mode == "agent"
    assert response.status == response.stage == "awaiting_agent"
    assert session.source.review_state == "confirmed"
    job = await get_job(session.source.id, AuthUser(id=session.source.owner_id), session)
    assert job.analysis_mode == "agent"


@pytest.mark.asyncio
async def test_keyless_meeting_review_analysis_replay_and_owner_boundary(database, monkeypatch):
    from app.modules.agent_workflows import service as workflow_module
    from app.modules.context_engine.application.extraction import ExtractionPipeline
    from app.modules.ingestion.application.pipeline import IngestionPipeline
    from tests.test_entity_resolution import FakeStore

    def forbidden(*_args, **_kwargs):
        raise AssertionError("server AI provider was invoked")

    monkeypatch.setattr(ExtractionPipeline, "extract", forbidden)
    monkeypatch.setattr(IngestionPipeline, "transcribe", forbidden)
    monkeypatch.setattr(IngestionPipeline, "index_source", forbidden)
    monkeypatch.setattr(IngestionPipeline, "embed_query", forbidden)
    graph = FakeStore()

    async def close_graph():
        pass

    graph.close = close_graph
    monkeypatch.setattr(workflow_module.Neo4jGraphStore, "from_settings", lambda _settings: graph)
    owner, outsider = uuid4(), uuid4()
    async with database() as session:
        settings = get_settings().model_copy(
            update={
                "neo4j_uri": "bolt://fake",
                "neo4j_username": "fake",
                "neo4j_password": SecretStr("fake"),
            }
        )
        workflow = AgentWorkflowService(session, settings)
        workspace = await workflow.create_workspace(owner_id=owner, name="Keyless")
        person = WorkspacePerson(
            owner_id=owner, workspace_id=workspace.id, name="민수", role="Owner"
        )
        session.add(person)
        await session.flush()
        project = WorkspaceProject(
            owner_id=owner,
            workspace_id=workspace.id,
            name="Search",
            owner_person_id=person.id,
        )
        session.add(project)
        await session.commit()
        source = await workflow.create_text_source(
            owner_id=owner,
            workspace_id=workspace.id,
            title="Meeting",
            text="old transcript",
            kind="meeting",
            project_ids=[project.id],
        )
        with pytest.raises(WorkflowError, match="Workspace not found"):
            await workflow.list_sources(owner_id=outsider, workspace_id=workspace.id)
        with pytest.raises(WorkflowError, match="Workspace not found"):
            await workflow.source_content(
                owner_id=outsider, workspace_id=workspace.id, source_id=source.id
            )
        with pytest.raises(WorkflowError, match="Transcript must be confirmed"):
            await workflow.analysis_context(
                owner_id=owner, workspace_id=workspace.id, source_id=source.id
            )
        await workflow.save_transcript(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=source.id,
            expected_revision=0,
            utterances=[
                {
                    "id": "u1",
                    "personId": str(person.id),
                    "speakerName": "민수",
                    "text": "캐시를 도입합니다.",
                }
            ],
        )
        confirmed = await workflow.confirm_transcript(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=source.id,
            expected_revision=1,
        )
        assert confirmed.review_state == "confirmed"
        assert confirmed.status == confirmed.stage == "awaiting_agent"
        context = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=source.id
        )
        assert context.text == "민수: 캐시를 도입합니다."
        assert context.directory["projects"][0]["ownerName"] == "민수"
        assert context.directory["people"][0]["id"] == str(person.id)
        proposal = extraction(context.text, kind="meeting")
        with pytest.raises(WorkflowError, match="Source quotation"):
            invalid = extraction("invented", kind="meeting")
            await workflow.submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=source.id,
                expected_revision=1,
                expected_fingerprint=context.fingerprint,
                result=invalid,
            )
        with pytest.raises(WorkflowError, match="Relation endpoint"):
            invalid_relation = extraction(context.text, kind="meeting")
            invalid_relation["relations"][0]["target"] = "foreign workspace decision"
            await workflow.submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=source.id,
                expected_revision=1,
                expected_fingerprint=context.fingerprint,
                result=invalid_relation,
            )
        with pytest.raises(WorkflowError, match="Source revision changed"):
            await workflow.submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=source.id,
                expected_revision=0,
                expected_fingerprint=context.fingerprint,
                result=proposal,
            )
        applied = await workflow.submit_analysis(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=source.id,
            expected_revision=1,
            expected_fingerprint=context.fingerprint,
            result=proposal,
        )
        assert applied.phase == "done" and not applied.already_applied
        replay = await workflow.submit_analysis(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=source.id,
            expected_revision=1,
            expected_fingerprint=context.fingerprint,
            result=proposal,
        )
        assert replay.already_applied
        chunks = (await session.exec(select(Chunk).where(Chunk.source_id == source.id))).all()
        timeline = (
            await session.exec(select(ContextRecord).where(ContextRecord.source_id == source.id))
        ).all()
        store = (
            await session.exec(
                select(ContextStoreRecord).where(ContextStoreRecord.workspace_id == workspace.id)
            )
        ).one()
        assert chunks and all(chunk.embedding is None for chunk in chunks)
        assert len(timeline) == 1 and timeline[0].title == "캐시 도입"
        assert len(store.decisions) == 1 and store.source_ids == [str(source.id)]
        assert {row["name"] for row in graph.rows("MERGE (e:Entity {id: row.id})")} >= {
            "민수",
            "캐시 도입",
        }
        content = await workflow.source_content(
            owner_id=owner, workspace_id=workspace.id, source_id=source.id
        )
        assert content.chunks[0].text and content.text == context.text
        with pytest.raises(WorkflowError, match="different analysis"):
            await workflow.submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=source.id,
                expected_revision=1,
                expected_fingerprint=context.fingerprint,
                result=extraction(context.text, kind="meeting", decision="캐시 변경"),
            )


@pytest.mark.asyncio
async def test_two_sources_preserve_summary_and_small_pool_concurrent_replay(database):
    owner = uuid4()
    async with database() as session:
        workflow = service(session)
        workspace = await workflow.create_workspace(owner_id=owner, name="Keyless")
        one = await workflow.create_text_source(
            owner_id=owner, workspace_id=workspace.id, title="One", text="민수는 캐시를 도입합니다."
        )
        context = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=one.id
        )
        proposal = extraction("민수는 캐시를 도입합니다.")

    async def submit():
        async with database() as session:
            return await service(session).submit_analysis(
                owner_id=owner,
                workspace_id=workspace.id,
                source_id=one.id,
                expected_revision=0,
                expected_fingerprint=context.fingerprint,
                result=proposal,
            )

    results = await asyncio.wait_for(asyncio.gather(submit(), submit()), timeout=20)
    assert sorted(item.already_applied for item in results) == [False, True]
    async with database() as session:
        workflow = service(session)
        two = await workflow.create_text_source(
            owner_id=owner, workspace_id=workspace.id, title="Two", text="민수는 검색을 개선합니다."
        )
        second_context = await workflow.analysis_context(
            owner_id=owner, workspace_id=workspace.id, source_id=two.id
        )
        await workflow.submit_analysis(
            owner_id=owner,
            workspace_id=workspace.id,
            source_id=two.id,
            expected_revision=0,
            expected_fingerprint=second_context.fingerprint,
            result=extraction("민수는 검색을 개선합니다.", decision="검색 개선"),
        )
        store = (
            await session.exec(
                select(ContextStoreRecord).where(ContextStoreRecord.workspace_id == workspace.id)
            )
        ).one()
        assert "캐시 도입" in store.summary and "검색 개선" in store.summary
        assert store.current_state == "캐시 도입"
        assert len(store.decisions) == 2

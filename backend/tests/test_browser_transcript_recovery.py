from uuid import uuid4

import pytest

from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.schemas import AgentUtterance
from app.modules.ingestion.application.transcript_recovery import recover_browser_transcript
from app.modules.ingestion.infrastructure.pg_jobs import ProcessingJob
from app.modules.workspaces.infrastructure.models import Source, Workspace, WorkspacePerson


class Session:
    def __init__(self):
        self.owner = uuid4()
        self.workspace = Workspace(owner_id=self.owner, name="Test")
        self.source = Source(
            owner_id=self.owner,
            workspace_id=self.workspace.id,
            kind="meeting",
            title="Failed recording",
            object_path="placeholder",
            content_type="audio/webm",
            size_bytes=500,
            status="failed",
            review_state="transcribing",
            processing_stage="transcribing",
            transcript_source="server",
            error_message="Transcription failed",
        )
        self.source.object_path = (
            f"{self.owner}/{self.workspace.id}/{self.source.id}/recording.webm"
        )
        self.job = ProcessingJob(source_id=self.source.id, status="failed")
        self.person = None
        self.commits = 0

    async def get(self, model, identifier, **kwargs):
        if model is Workspace and identifier == self.workspace.id:
            return self.workspace
        if model is Source and identifier == self.source.id:
            return self.source
        if model is ProcessingJob:
            return self.job
        if model is WorkspacePerson:
            return self.person
        return None

    def add(self, value):
        assert value is self.source

    async def commit(self):
        self.commits += 1


async def recover(session, **overrides):
    args = dict(
        owner_id=session.owner,
        workspace_id=session.workspace.id,
        source_id=session.source.id,
        revision=0,
        utterances=[AgentUtterance(id="a", speakerName="화자 1", text="검토할 문장")],
    )
    args.update(overrides)
    return await recover_browser_transcript(session, **args)


async def test_recovery_keeps_recording_and_requires_explicit_review():
    session = Session()
    original_path = session.source.object_path
    source = await recover(session)
    assert source.status == source.review_state == source.processing_stage == "awaiting_review"
    assert source.transcript_source == "browser"
    assert source.review_revision == 1
    assert source.object_path == original_path
    assert source.raw_transcript_text == "화자 1: 검토할 문장"
    assert source.confirmed_at is None and source.transcript_text is None
    assert source.error_message is None
    assert session.job.status == "failed"  # Confirmation, not recovery, rearms it.
    assert session.commits == 1
    with pytest.raises(WorkflowError) as exc:
        await recover(session)
    assert exc.value.status_code == 409


async def test_prior_original_is_not_lost():
    session = Session()
    session.source.raw_transcript_text = "원래 대본"
    session.source.raw_utterances = [{"id": "old", "text": "원래 대본"}]
    await recover(session)
    assert session.source.raw_transcript_text == "원래 대본"
    assert session.source.raw_utterances == [{"id": "old", "text": "원래 대본"}]


@pytest.mark.parametrize("job_status", ["pending", "running"])
async def test_active_worker_cannot_be_overwritten(job_status):
    session = Session()
    session.job.status = job_status
    with pytest.raises(WorkflowError) as exc:
        await recover(session)
    assert exc.value.status_code == 409 and session.commits == 0


@pytest.mark.parametrize(
    "field,value",
    [("status", "processing"), ("review_state", "confirmed"), ("analysis_mode", "agent")],
)
async def test_only_failed_server_transcription_can_recover(field, value):
    session = Session()
    setattr(session.source, field, value)
    with pytest.raises(WorkflowError) as exc:
        await recover(session)
    assert exc.value.status_code == 409 and session.commits == 0


async def test_foreign_owner_and_stale_revision_cannot_write():
    session = Session()
    for overrides, code in [({"owner_id": uuid4()}, 404), ({"revision": 9}, 409)]:
        with pytest.raises(WorkflowError) as exc:
            await recover(session, **overrides)
        assert exc.value.status_code == code
    assert session.commits == 0


async def test_empty_duplicate_and_foreign_person_are_rejected():
    session = Session()
    row = AgentUtterance(id="a", speakerName="speaker", text="text")
    for rows in [
        [],
        [row, row],
        [row.model_copy(update={"text": ""})],
        [row.model_copy(update={"person_id": uuid4()})],
    ]:
        with pytest.raises(WorkflowError) as exc:
            await recover(session, utterances=rows)
        assert exc.value.status_code == 422
    assert session.commits == 0

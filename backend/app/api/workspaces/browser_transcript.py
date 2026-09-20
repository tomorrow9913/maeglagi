"""HTTP adapter for a browser transcript recovered from a stored recording."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.workspaces.review import ReviewResponse, Session, review_payload_with_directory
from app.auth import CurrentUser
from app.modules.agent_workflows.errors import WorkflowError
from app.modules.agent_workflows.schemas import AgentUtterance
from app.modules.ingestion.application.transcript_recovery import recover_browser_transcript

router = APIRouter(prefix="/workspaces")


class BrowserTranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    utterances: list[AgentUtterance] = Field(min_length=1, max_length=1000)


@router.post(
    "/{workspace_id}/sources/{source_id}/review/browser-transcript",
    response_model=ReviewResponse,
)
async def save_browser_transcript(
    workspace_id: UUID,
    source_id: UUID,
    body: BrowserTranscriptRequest,
    user: CurrentUser,
    session: Session,
) -> ReviewResponse:
    try:
        source = await recover_browser_transcript(
            session,
            owner_id=user.id,
            workspace_id=workspace_id,
            source_id=source_id,
            revision=body.revision,
            utterances=body.utterances,
        )
    except WorkflowError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return await review_payload_with_directory(session, source)

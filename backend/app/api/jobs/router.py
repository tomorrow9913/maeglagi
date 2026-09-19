from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.jobs.schemas import JobResponse
from app.auth import CurrentUser
from app.core.database import get_session
from app.modules.workspaces.infrastructure.models import Source

router = APIRouter(prefix="/jobs")
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, user: CurrentUser, session: Session) -> JobResponse:
    source = await session.get(Source, job_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobResponse(
        id=source.id,
        source_id=source.id,
        source_kind=source.kind,
        transcript_source=source.transcript_source,
        analysis_mode=source.analysis_mode,
        status=source.status,
        progress=source.progress,
        stage=source.processing_stage,
        error_message=source.error_message,
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_session
from app.modules.workspaces.infrastructure.models import Source

router = APIRouter(prefix="/jobs")
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{job_id}")
async def get_job(job_id: UUID, user: CurrentUser, session: Session) -> dict[str, object]:
    source = await session.get(Source, job_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if source.status != "succeeded":
        source.status = "succeeded"
        session.add(source)
        await session.commit()
    return {
        "id": str(source.id),
        "sourceId": str(source.id),
        "sourceKind": source.kind,
        "status": "succeeded",
        "progress": 1,
        "stage": "completed",
    }

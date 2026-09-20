from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.auth.schemas import MeResponse
from app.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.modules.workspaces.application.account_deletion import (
    AccountDeletionError,
    delete_account_data,
)

router = APIRouter(prefix="/auth")


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    user: CurrentUser,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        await delete_account_data(user.id, session, settings, request.app.state.graph_store)
    except AccountDeletionError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

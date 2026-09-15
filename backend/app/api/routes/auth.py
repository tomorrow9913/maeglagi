from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthenticatedIdentity, get_authenticated_identity
from app.core.database import get_db
from app.modules.workspaces.application.identity_service import resolve_user
from app.schemas.auth import CurrentUserResponse

router = APIRouter(prefix="/auth")


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    identity: Annotated[AuthenticatedIdentity, Depends(get_authenticated_identity)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUserResponse:
    user = await resolve_user(session, identity)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        auth_provider=identity.provider,
    )

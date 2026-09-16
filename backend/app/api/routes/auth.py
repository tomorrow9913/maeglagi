from fastapi import APIRouter

from app.core.auth import CurrentUser
from app.schemas.auth import MeResponse

router = APIRouter(prefix="/auth")


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)

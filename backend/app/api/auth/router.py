from fastapi import APIRouter

from app.api.auth.schemas import MeResponse
from app.auth import CurrentUser

router = APIRouter(prefix="/auth")


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)

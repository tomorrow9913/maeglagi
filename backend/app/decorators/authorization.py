from collections.abc import Callable

from fastapi import HTTPException, status

from app.auth.dependencies import CurrentUser
from app.auth.models import AuthUser


def require_roles(*allowed_roles: str) -> Callable[[AuthUser], AuthUser]:
    """Build an authorization policy usable with FastAPI ``Depends``."""

    def authorize(user: CurrentUser) -> AuthUser:
        roles = user.metadata.get("roles", [])
        if isinstance(roles, str):
            roles = [roles]
        if not set(allowed_roles).intersection(roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return authorize

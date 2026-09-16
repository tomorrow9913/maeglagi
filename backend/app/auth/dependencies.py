from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthUser
from app.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthUser:
    if not settings.supabase_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Supabase is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token is required")

    headers = {
        "apikey": settings.supabase_publishable_key.get_secret_value(),
        "Authorization": f"Bearer {credentials.credentials}",
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user", headers=headers
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication service unavailable"
        ) from exc
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token")

    payload = response.json()
    return AuthUser(
        id=payload["id"],
        email=payload.get("email"),
        metadata=payload.get("user_metadata") or {},
    )


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]

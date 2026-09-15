from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    provider: str
    subject: str
    email: str | None
    display_name: str | None
    claims: dict[str, Any]


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    jwks_url = settings.auth_jwks_url or f"{settings.auth_issuer.rstrip('/')}/oauth/v2/keys"
    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
    options = {"verify_aud": settings.auth_audience is not None}
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.auth_audience,
        issuer=settings.auth_issuer.rstrip("/"),
        options=options,
    )


async def get_authenticated_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedIdentity:
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(credentials.credentials, settings)
        subject = claims["sub"]
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AuthenticatedIdentity(
        provider=settings.auth_provider,
        subject=subject,
        email=claims.get("email"),
        display_name=claims.get("name") or claims.get("preferred_username"),
        claims=claims,
    )

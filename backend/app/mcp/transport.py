"""ASGI boundary for authenticated Streamable HTTP MCP requests."""

import os
import re
from typing import Any
from urllib.parse import urlsplit

import sentry_sdk
from fastapi import HTTPException
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.datastructures import Headers, URLPath
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import BaseRoute, Match, NoMatchFound
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.models import AuthUser
from app.core.config import Settings

MAX_MCP_REQUEST_BYTES = 256 * 1024


def _public_url() -> str | None:
    return os.getenv("MAEGLAGI_MCP_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")


def _origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "*" in value
    ):
        raise ValueError("MCP origins must be exact HTTP(S) origins")
    return parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Use exact browser origins and an explicit deployment host allowlist."""
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"]
    origins = [_origin(value)[1] for value in settings.cors_origins]
    deployment = _public_url()
    if deployment:
        host, origin = _origin(deployment)
        hosts.append(host)
        origins.append(origin)
    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if render_host:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", render_host):
            raise ValueError("Invalid RENDER_EXTERNAL_HOSTNAME")
        hosts.append(render_host)
        origins.append(f"https://{render_host}")
    origins.extend(
        [
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
            "http://[::1]",
            "http://[::1]:8000",
        ]
    )
    return TransportSecuritySettings(
        allowed_hosts=list(dict.fromkeys(hosts)),
        allowed_origins=list(dict.fromkeys(origins)),
    )


class AuthenticatedMCP:
    """Authorize each HTTP request before the SDK parses or dispatches it."""

    def __init__(
        self, app: ASGIApp, settings: Settings, security: TransportSecuritySettings
    ) -> None:
        self.app = app
        self.settings = settings
        self.security = TransportSecurityMiddleware(security)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path not in {"/mcp", "/mcp/"}:
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return
        rejection = await self.security.validate_request(
            Request(scope), is_post=scope.get("method") == "POST"
        )
        if rejection is not None:
            await rejection(scope, receive, send)
            return
        headers = Headers(scope=scope)
        raw_authorization = headers.get("authorization", "")
        scheme, _, token = raw_authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 512:
            await PlainTextResponse(
                "MCP account token required",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        # Import at request time so token management remains owned by the auth layer.
        from app.auth.mcp import authenticate_mcp_token

        try:
            user = await authenticate_mcp_token(token, self.settings)
        except HTTPException:
            await PlainTextResponse(
                "Invalid MCP account token",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        except Exception as exc:
            sentry_sdk.capture_message(
                f"MCP authentication unexpected {type(exc).__name__}", level="error"
            )
            await PlainTextResponse("MCP authentication unavailable", status_code=503)(
                scope, receive, send
            )
            return
        if not isinstance(user, AuthUser):
            await PlainTextResponse("Invalid MCP account token", status_code=401)(
                scope, receive, send
            )
            return
        # A fresh state mapping prevents identity from persisting across requests.
        scope = {
            **scope,
            "state": {**scope.get("state", {}), "mcp_user": user},
            "maeglagi_parent_app": scope.get("app"),
        }
        await self.app(scope, receive, send)


class ExactMCPRoute(BaseRoute):
    """Give the SDK its exact path without a catch-all or trailing-slash redirect."""

    def __init__(self, app: ASGIApp | None = None) -> None:
        self.app = app

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http" and scope.get("path") in {"/mcp", "/mcp/"}:
            return Match.FULL, {}
        return Match.NONE, {}

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        if name == "mcp" and not path_params:
            return URLPath("/mcp", protocol="http")
        raise NoMatchFound(name, path_params)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self.app
        if app is None:
            await PlainTextResponse("MCP unavailable", status_code=503)(scope, receive, send)
            return
        await app(scope, receive, send)

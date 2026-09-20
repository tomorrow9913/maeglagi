from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException

from app.api import agent_uploads
from app.auth.models import AuthUser
from app.core.config import Settings
from app.core.database import get_session
from app.modules.workspaces.infrastructure.models import Workspace


async def test_agent_upload_reuses_validation_without_scheduling_ai(monkeypatch):
    owner = uuid4()
    workspace = Workspace(owner_id=owner, name="Agent files")
    sources = []
    session = SimpleNamespace(
        get=AsyncMock(return_value=workspace), add=sources.append, commit=AsyncMock()
    )
    application = FastAPI()
    application.state.settings = Settings(_env_file=None, max_upload_bytes=100)
    application.include_router(agent_uploads.router, prefix="/api/v1")

    async def sessions():
        yield session

    application.dependency_overrides[get_session] = sessions
    authenticate = AsyncMock(return_value=AuthUser(id=owner))
    storage = AsyncMock()
    monkeypatch.setattr(agent_uploads, "authenticate_mcp_token", authenticate)
    monkeypatch.setattr(agent_uploads, "store_source_bytes", storage)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(application), base_url="http://test"
    ) as client:
        path = f"/api/v1/agent-uploads/workspaces/{workspace.id}"
        headers = {"Authorization": "Bearer synthetic-test-token"}
        missing = await client.post(
            path,
            data={"kind": "meeting"},
            files={"file": ("a.wav", b"RIFF0000WAVEdata", "audio/wav")},
        )
        assert missing.status_code == 401
        response = await client.post(
            path,
            headers=headers,
            data={"kind": "meeting"},
            files={"file": ("a.wav", b"RIFF0000WAVEdata", "audio/wav")},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "awaiting_agent"
        assert response.json()["analysisMode"] == "agent"
        stored = sources[-1]
        assert stored.analysis_mode == "agent" and stored.review_state == "awaiting_review"
        assert stored.object_path.startswith(f"{owner}/{workspace.id}/{stored.id}/")
        assert stored.analysis_checkpoint is None
        assert "token" not in response.text
        assert storage.await_count == 1
        invalid = await client.post(
            path,
            headers=headers,
            data={"kind": "meeting"},
            files={"file": ("a.wav", b"not audio", "audio/wav")},
        )
        assert invalid.status_code == 422
        oversized = await client.post(
            path,
            headers=headers,
            data={"kind": "document"},
            files={"file": ("a.txt", b"a" * 101, "text/plain")},
        )
        assert oversized.status_code == 413
        assert storage.await_count == 1
        workspace.owner_id = uuid4()
        denied = await client.post(
            path,
            headers=headers,
            data={"kind": "document"},
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert denied.status_code == 404
        assert storage.await_count == 1
        authenticate.side_effect = HTTPException(401, "Invalid or expired MCP token")
        revoked = await client.post(
            path,
            headers=headers,
            data={"kind": "document"},
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert revoked.status_code == 401
        assert storage.await_count == 1

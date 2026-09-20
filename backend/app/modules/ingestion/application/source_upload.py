"""Validated source uploads shared by HTTP and external-agent adapters."""

from collections.abc import Awaitable, Callable
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.modules.ingestion.application.upload_validation import (
    InvalidUploadError,
    UnsupportedUploadError,
    validate_document,
    validate_recording,
)
from app.modules.workspaces.infrastructure.models import Source, Workspace


class UploadServiceError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


async def store_source_bytes(
    source: Source, content: bytes, *, settings: Settings, storage_token: str
) -> None:
    if not storage_token:
        raise UploadServiceError(503, "Storage is not configured")
    storage_url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{quote(settings.supabase_storage_bucket, safe='')}/{quote(source.object_path, safe='/')}"
    )
    headers = {
        "apikey": settings.supabase_publishable_key.get_secret_value(),
        "Authorization": f"Bearer {storage_token}",
        "Content-Type": source.content_type,
        "x-upsert": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(storage_url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise UploadServiceError(503, "Storage unavailable") from exc
    if response.status_code not in {200, 201}:
        raise UploadServiceError(502, "Storage upload failed")


class SourceUploadService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def upload(
        self,
        *,
        owner_id: UUID,
        workspace_id: UUID,
        filename: str | None,
        content_type: str | None,
        content: bytes,
        kind: str,
        write_object: Callable[[Source, bytes], Awaitable[None]],
    ) -> Source:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None or workspace.owner_id != owner_id:
            raise UploadServiceError(404, "Workspace not found")
        if kind not in {"document", "meeting"}:
            raise UploadServiceError(422, "Invalid source kind")
        if not content:
            raise UploadServiceError(400, "Empty file")
        if len(content) > self.settings.max_upload_bytes:
            raise UploadServiceError(413, "File is too large")
        filename = filename or ("recording.webm" if kind == "meeting" else "document")
        filename = filename.replace("/", "_").replace("\\", "_")
        if len(filename) > 255 or any(ord(char) < 32 for char in filename):
            raise UploadServiceError(422, "Invalid filename")
        try:
            if kind == "document":
                validate_document(filename, content_type, content)
            else:
                extension = validate_recording(filename, content_type, content)
                if filename.lower().endswith(".webm") and extension == ".mp4":
                    filename = filename[:-5] + ".mp4"
        except UnsupportedUploadError as exc:
            raise UploadServiceError(415, str(exc)) from exc
        except InvalidUploadError as exc:
            raise UploadServiceError(422, str(exc)) from exc
        source = Source(
            workspace_id=workspace.id,
            owner_id=owner_id,
            kind=kind,
            title=filename,
            object_path="pending",
            content_type=content_type or "application/octet-stream",
            size_bytes=len(content),
        )
        source.object_path = f"{owner_id}/{workspace.id}/{source.id}/{filename}"
        await write_object(source, content)
        self.session.add(source)
        return source

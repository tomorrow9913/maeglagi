"""Short-lived private Storage links for an already authorized source."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.modules.workspaces.infrastructure.models import Source


class MediaAccessError(RuntimeError):
    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.status_code = status_code


class SignedMediaUrl(BaseModel):
    url: str
    expires_at: datetime = Field(serialization_alias="expiresAt")


async def signed_media_url(source: Source, settings: Settings) -> SignedMediaUrl:
    stored_path = f"{source.owner_id}/{source.workspace_id}/{source.id}/"
    if source.size_bytes <= 0 or not source.object_path.startswith(stored_path):
        raise MediaAccessError("Stored media not found", 404)
    key = settings.supabase_service_role_key.get_secret_value()
    if not key:
        raise MediaAccessError("Media playback unavailable", 503)
    bucket = quote(settings.supabase_storage_bucket, safe="")
    path = quote(source.object_path, safe="/")
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/sign/{bucket}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={"expiresIn": 300},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
        response.raise_for_status()
        signed = response.json().get("signedURL") or response.json().get("signedUrl")
    except (httpx.HTTPError, ValueError) as exc:
        raise MediaAccessError("Media playback unavailable", 503) from exc
    if not isinstance(signed, str) or not signed.startswith(f"/object/sign/{bucket}/{path}?"):
        raise MediaAccessError("Invalid media URL", 502)
    return SignedMediaUrl(
        url=f"{settings.supabase_url.rstrip('/')}/storage/v1{signed}",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

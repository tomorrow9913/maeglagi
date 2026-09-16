from typing import Literal

import httpx
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.database import engine
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore

StoreStatus = Literal["ok", "error", "disabled"]


async def check_storage_health(settings: Settings | None = None) -> dict[str, StoreStatus]:
    settings = settings or get_settings()
    checks: dict[str, StoreStatus] = {
        "objectStorage": "disabled",
        "postgresql": "error",
        "vector": "error",
        "graph": "error",
    }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
            checks["postgresql"] = "ok"
            vector_enabled = await connection.scalar(
                text("select exists(select 1 from pg_extension where extname = 'vector')")
            )
            checks["vector"] = "ok" if vector_enabled else "error"
    except Exception:  # readiness must report dependency failure instead of crashing
        pass

    if settings.supabase_enabled:
        storage_url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/authenticated/"
        headers = {
            "apikey": settings.supabase_publishable_key.get_secret_value(),
            "Authorization": f"Bearer {settings.supabase_publishable_key.get_secret_value()}",
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.head(storage_url, headers=headers)
            checks["objectStorage"] = "ok" if response.status_code < 500 else "error"
        except httpx.HTTPError:
            checks["objectStorage"] = "error"

    if settings.neo4j_enabled:
        graph_store = Neo4jGraphStore.from_settings(settings)
        try:
            await graph_store.verify_connectivity()
            checks["graph"] = "ok"
        except Exception:  # readiness reports graph failure without exposing credentials
            checks["graph"] = "error"
        finally:
            await graph_store.close()

    return checks

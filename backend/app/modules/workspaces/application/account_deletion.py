"""Remove account-owned external data before deleting its Supabase identity."""

import logging
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import delete, text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.core.credentials import credential_vault
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore
from app.modules.workspaces.infrastructure.models import (
    ProviderCredential,
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceMember,
)

logger = logging.getLogger(__name__)


class AccountDeletionError(RuntimeError):
    pass


async def delete_account_data(
    owner_id: UUID, session: AsyncSession, settings: Settings, graph: Neo4jGraphStore | None
) -> None:
    """Delete storage, graph, Vault secrets and finally the auth user.

    The auth deletion cascades all public rows that reference auth.users. External
    deletions are idempotent, so a failed attempt can be retried with the same user.
    """
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise AccountDeletionError("Account deletion is unavailable")

    workspaces = (
        await session.exec(select(Workspace.id).where(Workspace.owner_id == owner_id))
    ).all()
    credentials = (
        await session.exec(
            select(ProviderCredential.vault_secret_id).where(
                ProviderCredential.owner_id == owner_id
            )
        )
    ).all()
    # Include objects from interrupted uploads that never became Source rows.
    paths = (
        (
            await session.execute(
                text(
                    "select name from storage.objects "
                    "where bucket_id = :bucket and name like :prefix"
                ),
                {"bucket": settings.supabase_storage_bucket, "prefix": f"{owner_id}/%"},
            )
        )
        .scalars()
        .all()
    )
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    base = settings.supabase_url.rstrip("/")
    bucket = quote(settings.supabase_storage_bucket, safe="")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for start in range(0, len(paths), 1000):
                response = await client.request(
                    "DELETE",
                    f"{base}/storage/v1/object/{bucket}",
                    headers=headers,
                    json={"prefixes": paths[start : start + 1000]},
                )
                response.raise_for_status()
            if graph is not None:
                for workspace_id in workspaces:
                    await graph.execute(
                        "MATCH (e:Entity {workspace_id: $workspace_id}) DETACH DELETE e",
                        {"workspace_id": str(workspace_id)},
                    )
            # Vault secrets have no FK to auth.users. Keep their removal pending
            # so a failed Auth request rolls it back and leaves keys available.
            for secret_id in credentials:
                if secret_id is not None:
                    await credential_vault.delete(session, secret_id=secret_id)
            # Membership is account-scoped even when another person owns the workspace.
            # Keep the audit event itself as evidence, but remove the deleted account's email.
            await session.execute(
                delete(WorkspaceMember).where(WorkspaceMember.user_id == owner_id)
            )
            await session.execute(
                update(WorkspaceAuditEvent)
                .where(WorkspaceAuditEvent.actor_id == owner_id)
                .values(actor_email=None)
            )
            # PGMQ event rows outlive source rows and contain account IDs.
            for queue_table in ("pgmq.q_source_events", "pgmq.a_source_events"):
                exists = (
                    await session.execute(
                        text("select to_regclass(:table_name)"), {"table_name": queue_table}
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    await session.execute(
                        text(f"delete from {queue_table} where message->>'owner_id' = :owner_id"),
                        {"owner_id": str(owner_id)},
                    )
            response = await client.delete(
                f"{base}/auth/v1/admin/users/{owner_id}", headers=headers
            )
            response.raise_for_status()
            await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Account deletion failed for user %s", owner_id)
        raise AccountDeletionError("계정 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.") from exc

"""Storage boundary for provider credential secrets.

Implementations may use Supabase Vault, a KMS-backed envelope store, or another
server-side secret store. Callers depend only on this contract and never receive
storage-specific identifiers other than the opaque UUID persisted with a credential.
"""

from typing import Protocol
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession


class CredentialVault(Protocol):
    """Persist and recover provider secrets without exposing storage details."""

    async def create(
        self,
        session: AsyncSession,
        *,
        secret: str,
        credential_id: UUID,
        workspace_id: UUID | None,
        provider: str,
    ) -> UUID: ...

    async def update(self, session: AsyncSession, *, secret_id: UUID, secret: str) -> None: ...

    async def delete(self, session: AsyncSession, *, secret_id: UUID) -> None: ...

    async def reveal(self, session: AsyncSession, *, secret_id: UUID) -> str: ...

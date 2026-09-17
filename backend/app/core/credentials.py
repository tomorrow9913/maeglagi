import base64
import hashlib
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings


class CredentialUnavailableError(RuntimeError):
    """Raised when a stored provider credential cannot be recovered."""


class SupabaseCredentialVault:
    """Small application boundary around the Supabase Vault SQL API."""

    async def create(
        self,
        session: AsyncSession,
        *,
        secret: str,
        credential_id: UUID,
        workspace_id: UUID,
        provider: str,
    ) -> UUID:
        result = await session.execute(
            text("select vault.create_secret(:secret, :name, :description)"),
            {
                "secret": secret,
                "name": f"provider-credential:{credential_id}",
                "description": f"workspace={workspace_id};provider={provider}",
            },
        )
        return result.scalar_one()

    async def update(self, session: AsyncSession, *, secret_id: UUID, secret: str) -> None:
        await session.execute(
            text("select vault.update_secret(:secret_id, :secret)"),
            {"secret_id": secret_id, "secret": secret},
        )

    async def reveal(self, session: AsyncSession, *, secret_id: UUID) -> str:
        result = await session.execute(
            text("select decrypted_secret from vault.decrypted_secrets where id = :secret_id"),
            {"secret_id": secret_id},
        )
        secret = result.scalar_one_or_none()
        if not secret:
            raise CredentialUnavailableError("Vault secret is missing or inaccessible")
        return str(secret)


credential_vault = SupabaseCredentialVault()


def _legacy_fernet() -> Fernet:
    """Read credentials written before the Supabase Vault migration."""
    secret = get_settings().app_secret_key.get_secret_value().encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


async def store_credential_secret(
    session: AsyncSession,
    *,
    secret: str,
    credential_id: UUID,
    workspace_id: UUID,
    provider: str,
) -> UUID:
    return await credential_vault.create(
        session,
        secret=secret,
        credential_id=credential_id,
        workspace_id=workspace_id,
        provider=provider,
    )


async def resolve_credential_secret(session: AsyncSession, credential: object) -> str:
    vault_secret_id = getattr(credential, "vault_secret_id", None)
    if vault_secret_id is not None:
        return await credential_vault.reveal(session, secret_id=vault_secret_id)

    # Temporary compatibility path. Updating the credential moves it into Vault.
    encrypted_secret = getattr(credential, "encrypted_secret", None)
    if not encrypted_secret:
        raise CredentialUnavailableError("Credential has no stored secret")
    try:
        return _legacy_fernet().decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as exc:
        raise CredentialUnavailableError("Legacy credential cannot be decrypted") from exc

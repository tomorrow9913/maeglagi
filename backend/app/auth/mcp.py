"""Account-scoped MCP credentials. These tokens never authenticate REST requests."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, String, func, text, update
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import AuthUser
from app.core.config import Settings
from app.core.database import session_factory

TOKEN_PATTERN = re.compile(r"mgmcp_[A-Za-z0-9_-]{43}\Z")
TOKEN_LIFETIME = timedelta(days=90)
MAX_ACTIVE_TOKENS = 20


class McpToken(SQLModel, table=True):
    __tablename__ = "mcp_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(index=True)
    label: str = Field(max_length=80)
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True))
    token_hint: str = Field(max_length=6)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


async def issue_token(session: AsyncSession, owner_id: UUID, label: str) -> tuple[McpToken, str]:
    """Return a secret once; only its SHA-256 digest is persisted."""
    label = label.strip()
    if not label or len(label) > 80 or any(ord(char) < 32 for char in label):
        raise HTTPException(422, "연결 이름을 1~80자로 입력해 주세요.")
    lock_key = int.from_bytes(
        hashlib.sha256(b"mcp-token:" + owner_id.bytes).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    count = (
        await session.exec(
            select(func.count())
            .select_from(McpToken)
            .where(
                McpToken.owner_id == owner_id,
                McpToken.revoked_at.is_(None),
                McpToken.expires_at > func.now(),
            )
        )
    ).one()
    if count >= MAX_ACTIVE_TOKENS:
        raise HTTPException(409, "사용하지 않는 MCP 연결을 해제한 뒤 추가해 주세요.")
    secret = "mgmcp_" + secrets.token_urlsafe(32)
    item = McpToken(
        owner_id=owner_id,
        label=label,
        token_hash=token_digest(secret),
        token_hint=secret[-6:],
        expires_at=datetime.now(UTC) + TOKEN_LIFETIME,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item, secret


async def authenticate_mcp_token(token: str, settings: Settings) -> AuthUser:
    """Check expiration/revocation on every request without accepting Supabase JWTs."""
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(401, "Invalid or expired MCP token")
    async with session_factory() as session:
        # A conditional UPDATE is atomic with revocation and records successful use.
        result = await session.execute(
            update(McpToken)
            .where(
                McpToken.token_hash == token_digest(token),
                McpToken.revoked_at.is_(None),
                McpToken.expires_at > func.now(),
            )
            .values(last_used_at=func.now())
            .returning(McpToken.owner_id)
        )
        owner_id = result.scalar_one_or_none()
        await session.commit()
    if owner_id is None:
        raise HTTPException(401, "Invalid or expired MCP token")
    return AuthUser(id=owner_id)

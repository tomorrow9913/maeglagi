"""Account-scoped MCP credentials. These tokens never authenticate REST requests."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, String, func, or_, text, update
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.models import AuthUser
from app.core.config import Settings
from app.core.database import session_factory

TOKEN_PATTERN = re.compile(r"mgmcp_[A-Za-z0-9_-]{43}\Z")
DEFAULT_TOKEN_LIFETIME_DAYS = 90
MAX_TOKEN_LIFETIME_DAYS = 365
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
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def validate_lifetime(days: int | None) -> None:
    if days is None:
        return
    if (
        isinstance(days, bool)
        or not isinstance(days, int)
        or not 1 <= days <= MAX_TOKEN_LIFETIME_DAYS
    ):
        raise HTTPException(422, "토큰 유효 기간은 1~365일로 설정해 주세요.")


async def issue_token(
    session: AsyncSession,
    owner_id: UUID,
    label: str,
    expires_in_days: int | None = DEFAULT_TOKEN_LIFETIME_DAYS,
) -> tuple[McpToken, str]:
    """Return a secret once; only its SHA-256 digest is persisted."""
    label = label.strip()
    if not label or len(label) > 80 or any(ord(char) < 32 for char in label):
        raise HTTPException(422, "연결 이름을 1~80자로 입력해 주세요.")
    validate_lifetime(expires_in_days)
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
                or_(McpToken.expires_at.is_(None), McpToken.expires_at > func.now()),
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
        expires_at=(
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        ),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item, secret


async def extend_token(
    session: AsyncSession, owner_id: UUID, token_id: UUID, expires_in_days: int | None
) -> McpToken:
    """Extend a live token to at least N days from now; never revive or shorten it."""
    validate_lifetime(expires_in_days)
    new_expiry = (
        datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )
    statement = update(McpToken).where(
        McpToken.id == token_id,
        McpToken.owner_id == owner_id,
        McpToken.revoked_at.is_(None),
        McpToken.expires_at.is_not(None),
        McpToken.expires_at > func.now(),
    )
    if new_expiry is not None:
        statement = statement.where(McpToken.expires_at < new_expiry)
    result = await session.execute(statement.values(expires_at=new_expiry).returning(McpToken.id))
    if result.scalar_one_or_none() is None:
        existing = (
            await session.exec(
                select(McpToken.id).where(
                    McpToken.id == token_id,
                    McpToken.owner_id == owner_id,
                    McpToken.revoked_at.is_(None),
                    or_(McpToken.expires_at.is_(None), McpToken.expires_at > func.now()),
                )
            )
        ).first()
        if existing is None:
            raise HTTPException(
                404, "활성 MCP 토큰을 찾을 수 없습니다. 만료된 토큰은 새로 발급해 주세요."
            )
        raise HTTPException(409, "선택한 기간으로는 현재 만료일이 늘어나지 않습니다.")
    await session.commit()
    item = await session.get(McpToken, token_id)
    assert item is not None
    return item


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
                or_(McpToken.expires_at.is_(None), McpToken.expires_at > func.now()),
            )
            .values(last_used_at=func.now())
            .returning(McpToken.owner_id)
        )
        owner_id = result.scalar_one_or_none()
        await session.commit()
    if owner_id is None:
        raise HTTPException(401, "Invalid or expired MCP token")
    return AuthUser(id=owner_id)

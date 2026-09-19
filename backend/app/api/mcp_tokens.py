"""Signed-in account management of revocable MCP connections."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import CurrentUser
from app.auth.mcp import McpToken, issue_token
from app.core.database import get_session

router = APIRouter(prefix="/mcp-tokens", tags=["mcp-connections"])
Session = Annotated[AsyncSession, Depends(get_session)]


class TokenInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    label: str
    token_hint: str = Field(serialization_alias="tokenHint")
    created_at: datetime = Field(serialization_alias="createdAt")
    last_used_at: datetime | None = Field(serialization_alias="lastUsedAt")
    expires_at: datetime = Field(serialization_alias="expiresAt")


class TokenList(BaseModel):
    items: list[TokenInfo]


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)


class IssuedToken(BaseModel):
    item: TokenInfo
    token: str


@router.get("", response_model=TokenList)
async def list_tokens(user: CurrentUser, session: Session, response: Response) -> TokenList:
    response.headers["Cache-Control"] = "no-store"
    result = await session.exec(
        select(McpToken)
        .where(
            McpToken.owner_id == user.id,
            McpToken.revoked_at.is_(None),
        )
        .order_by(McpToken.created_at.desc())
    )
    return TokenList(items=[TokenInfo.model_validate(item) for item in result.all()])


@router.post("", response_model=IssuedToken, status_code=201)
async def create_token(
    body: TokenCreate, user: CurrentUser, session: Session, response: Response
) -> IssuedToken:
    response.headers["Cache-Control"] = "no-store"
    item, secret = await issue_token(session, user.id, body.label)
    return IssuedToken(item=TokenInfo.model_validate(item), token=secret)


@router.delete("/{token_id}", status_code=204)
async def revoke_token(token_id: UUID, user: CurrentUser, session: Session) -> Response:
    item = await session.get(McpToken, token_id)
    if item is None or item.owner_id != user.id:
        raise HTTPException(404, "MCP connection not found")
    await session.execute(
        update(McpToken)
        .where(McpToken.id == token_id, McpToken.owner_id == user.id, McpToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await session.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

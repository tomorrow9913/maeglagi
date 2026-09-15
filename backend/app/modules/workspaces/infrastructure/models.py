import uuid
from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)
    identities: list["UserIdentity"] = Relationship(back_populates="user")


class UserIdentity(SQLModel, table=True):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE")
    provider: str = Field(max_length=50)
    provider_subject: str = Field(max_length=255)
    email_at_link_time: str | None = Field(default=None, max_length=320)
    created_at: datetime = Field(default_factory=utc_now)
    user: User | None = Relationship(back_populates="identities")


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=200)
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceMembership(SQLModel, table=True):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id", ondelete="CASCADE")
    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE")
    role: str = Field(default="member", max_length=50)
    created_at: datetime = Field(default_factory=utc_now)

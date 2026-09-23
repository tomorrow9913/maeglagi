from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None
    last_sign_in_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

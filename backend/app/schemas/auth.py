from uuid import UUID

from pydantic import BaseModel


class CurrentUserResponse(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None
    auth_provider: str

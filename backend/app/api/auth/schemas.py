from uuid import UUID

from pydantic import BaseModel


class MeResponse(BaseModel):
    id: UUID
    email: str | None

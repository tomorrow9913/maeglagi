from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    created_at: datetime = Field(serialization_alias="createdAt")
    source_count: int = Field(default=0, serialization_alias="sourceCount")

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    workspace_id: UUID = Field(serialization_alias="workspaceId")
    kind: str
    title: str
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    size_bytes: int = Field(serialization_alias="sizeBytes")

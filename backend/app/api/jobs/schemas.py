from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    source_id: UUID = Field(serialization_alias="sourceId")
    source_kind: str = Field(serialization_alias="sourceKind")
    status: Literal["succeeded"] = "succeeded"
    progress: Literal[1] = 1
    stage: Literal["completed"] = "completed"

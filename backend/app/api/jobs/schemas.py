from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    source_id: UUID = Field(serialization_alias="sourceId")
    source_kind: str = Field(serialization_alias="sourceKind")
    transcript_source: str | None = Field(default=None, serialization_alias="transcriptSource")
    status: str
    progress: float = Field(ge=0, le=1)
    stage: str
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")

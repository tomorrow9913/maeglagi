from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.workspaces.domain.source_state import ProcessingStage, SourceStatus


class JobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    source_id: UUID = Field(serialization_alias="sourceId")
    source_kind: str = Field(serialization_alias="sourceKind")
    transcript_source: str | None = Field(default=None, serialization_alias="transcriptSource")
    status: SourceStatus
    analysis_mode: str = Field(default="server", serialization_alias="analysisMode")
    progress: float = Field(ge=0, le=1)
    stage: ProcessingStage
    error_message: str | None = Field(default=None, serialization_alias="errorMessage")

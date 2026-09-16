from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class StorageChecks(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    object_storage: Literal["ok", "error", "disabled"] = Field(alias="objectStorage")
    postgresql: Literal["ok", "error", "disabled"]
    vector: Literal["ok", "error", "disabled"]
    graph: Literal["ok", "error", "disabled"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: StorageChecks

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CredentialInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    api_key: str = Field(min_length=1, validation_alias="apiKey")
    label: str = Field(default="기본", min_length=1, max_length=80)


class CredentialValidation(BaseModel):
    valid: bool
    message: str


class CredentialResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    provider: str
    label: str
    key_hint: str = Field(serialization_alias="keyHint")
    status: str
    is_default: bool = Field(serialization_alias="isDefault")
    updated_at: datetime = Field(serialization_alias="updatedAt")

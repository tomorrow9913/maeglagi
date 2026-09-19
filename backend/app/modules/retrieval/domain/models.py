from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GraphEvidence(BaseModel):
    source_id: UUID
    chunk_id: UUID | None = None
    timestamp: datetime | None = None


class GraphEntity(BaseModel):
    id: UUID
    workspace_id: UUID
    kind: str
    name: str
    evidence: GraphEvidence
    # Other spellings of the same entity; `keys` are their normalized forms used for merging.
    aliases: list[str] = Field(default_factory=list)
    keys: list[str] = Field(default_factory=list)
    # Normalized identifying details (email etc.). Names alone never merge people who differ here.
    identifiers: list[str] = Field(default_factory=list)


class GraphRelation(BaseModel):
    id: UUID
    workspace_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    kind: str
    evidence: GraphEvidence

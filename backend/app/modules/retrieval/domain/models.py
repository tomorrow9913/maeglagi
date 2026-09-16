from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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


class GraphRelation(BaseModel):
    id: UUID
    workspace_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    kind: str
    evidence: GraphEvidence

"""Import every SQLModel table so Alembic sees one complete metadata graph."""

from sqlmodel import SQLModel

from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
from app.modules.ingestion.infrastructure.pg_jobs import ProcessingJob
from app.modules.workspaces.infrastructure.models import (
    ProjectMember,
    ProviderCredential,
    Source,
    SourcePerson,
    SourceProject,
    Workspace,
    WorkspacePerson,
    WorkspaceProject,
)

__all__ = [
    "Chunk",
    "ContextRecord",
    "ContextStoreRecord",
    "ProviderCredential",
    "ProjectMember",
    "ProcessingJob",
    "SQLModel",
    "Source",
    "SourcePerson",
    "SourceProject",
    "Workspace",
    "WorkspacePerson",
    "WorkspaceProject",
]

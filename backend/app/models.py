"""Import every SQLModel table so Alembic sees one complete metadata graph."""

from sqlmodel import SQLModel

from app.modules.context_engine.infrastructure.models import (
    Chunk,
    ContextRecord,
    ContextStoreRecord,
)
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
    "SQLModel",
    "Source",
    "SourcePerson",
    "SourceProject",
    "Workspace",
    "WorkspacePerson",
    "WorkspaceProject",
]

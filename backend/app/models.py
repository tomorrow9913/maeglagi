"""Import every SQLModel table so Alembic sees one complete metadata graph."""

from sqlmodel import SQLModel

from app.modules.context_engine.infrastructure.models import Chunk, ContextRecord
from app.modules.workspaces.infrastructure.models import ProviderCredential, Source, Workspace

__all__ = [
    "Chunk",
    "ContextRecord",
    "ProviderCredential",
    "SQLModel",
    "Source",
    "Workspace",
]

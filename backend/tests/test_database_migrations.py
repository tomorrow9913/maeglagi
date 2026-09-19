from app.core.database import normalize_database_url
from app.models import SQLModel


def test_all_sqlmodel_tables_are_registered_for_alembic() -> None:
    assert set(SQLModel.metadata.tables) == {
        "workspaces",
        "sources",
        "provider_credentials",
        "chunks",
        "contexts",
        "context_stores",
    }


def test_database_url_normalization_handles_supabase_copy_paste() -> None:
    assert (
        normalize_database_url(
            "postgresql+asyncpg://postgresql://postgres.ref:secret@pooler.example:5432/postgres"
        )
        == "postgresql+asyncpg://postgres.ref:secret@pooler.example:5432/postgres"
    )
    assert (
        normalize_database_url("postgresql://postgres.ref:secret@pooler.example:5432/postgres")
        == "postgresql+asyncpg://postgres.ref:secret@pooler.example:5432/postgres"
    )

from app.core.database import normalize_database_url
from app.models import SQLModel
from app.modules.workspaces.domain.source_state import ProcessingStage, ReviewState, SourceStatus


def test_all_sqlmodel_tables_are_registered_for_alembic() -> None:
    assert set(SQLModel.metadata.tables) == {
        "workspaces",
        "sources",
        "provider_credentials",
        "chunks",
        "contexts",
        "context_stores",
        "workspace_people",
        "workspace_projects",
        "project_members",
        "source_projects",
        "source_people",
        "processing_jobs",
        "mcp_tokens",
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


def test_source_workflow_enums_remain_string_compatible_without_native_pg_enum() -> None:
    assert SourceStatus.PROCESSING == "processing"
    assert ReviewState.AWAITING_REVIEW == "awaiting_review"
    assert ProcessingStage.TRANSCRIBING == "transcribing"
    sources = SQLModel.metadata.tables["sources"]
    assert sources.c.status.type.__class__.__name__ == "String"
    assert sources.c.processing_stage.type.__class__.__name__ == "String"
    assert sources.c.review_state.type.__class__.__name__ == "String"

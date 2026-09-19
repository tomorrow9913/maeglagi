from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Maeglagi API"
    app_version: str = "0.1.0"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"
    app_secret_key: SecretStr = SecretStr("local-development-only-secret-key")
    database_url: str = "postgresql+asyncpg://maeglagi:maeglagi@localhost:5432/maeglagi"
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_storage_bucket: str = "sources"
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: SecretStr = SecretStr("")
    max_upload_bytes: int = 50 * 1024 * 1024
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = "mock"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    transcription_model: str = "whisper-1"
    extraction_model: str = "gpt-4o-mini"
    answer_model: str = "gpt-4o-mini"
    # The model each provider preselects per job, before and after a key is entered. Operators
    # keep it current (env PROVIDER_DEFAULT_MODELS takes JSON). A default the key does not offer,
    # or that the provider has retired, is simply skipped.
    provider_default_models: dict[str, dict[str, str]] = {
        "openai": {
            "answer": "gpt-4o-mini",
            "extraction": "gpt-4o-mini",
            "embedding": "text-embedding-3-small",
            "transcription": "whisper-1",
        },
        "anthropic": {"answer": "claude-haiku-4-5", "extraction": "claude-haiku-4-5"},
        "nvidia": {
            "answer": "meta/llama-3.1-8b-instruct",
            "extraction": "meta/llama-3.1-8b-instruct",
        },
    }
    # Optional per-provider runtime fallback overrides. This keeps deployments using
    # PROVIDER_FALLBACK_MODELS compatible with the catalog's provider defaults.
    provider_fallback_models: dict[str, dict[str, str]] = {}
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    rate_limit: str = "120/minute"
    rate_limit_storage_uri: str = "memory://"
    log_level: str = "INFO"
    celery_broker_url: SecretStr = SecretStr("memory://")
    celery_task_always_eager: bool = False

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key.get_secret_value())

    @property
    def neo4j_enabled(self) -> bool:
        return bool(
            self.neo4j_uri and self.neo4j_username and self.neo4j_password.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

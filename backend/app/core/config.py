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
    supabase_storage_bucket: str = "sources"
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: SecretStr = SecretStr("")
    max_upload_bytes: int = 50 * 1024 * 1024
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = "mock"
    sentry_dsn: SecretStr = SecretStr("")
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    rate_limit: str = "120/minute"
    rate_limit_storage_uri: str = "memory://"
    log_level: str = "INFO"

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

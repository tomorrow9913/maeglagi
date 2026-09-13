from functools import lru_cache

from pydantic import SecretStr
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
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()

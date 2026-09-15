from functools import lru_cache

from pydantic import SecretStr, field_validator
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
    database_auto_create: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = "mock"
    auth_enabled: bool = False
    auth_provider: str = "zitadel"
    auth_issuer: str = "http://localhost:8081"
    auth_audience: str | None = None
    auth_jwks_url: str | None = None

    @field_validator("auth_audience", "auth_jwks_url", mode="before")
    @classmethod
    def empty_string_as_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()

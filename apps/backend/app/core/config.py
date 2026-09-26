"""Application settings loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {"", "change-me-access-secret", "change-me-refresh-secret", "dev-only-insecure-access-secret-change-me-0001", "dev-only-insecure-refresh-secret-change-me-0002"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "SYMBIO API"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./var/symbio.db"
    sql_echo: bool = False

    jwt_secret: str = "dev-only-insecure-access-secret-change-me-0001"
    jwt_refresh_secret: str = "dev-only-insecure-refresh-secret-change-me-0002"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    password_reset_ttl_minutes: int = 30
    email_verification_ttl_hours: int = 48

    redis_url: str | None = None

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./var/storage"
    storage_bucket: str = "symbio-documents"
    storage_endpoint_url: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    max_upload_mb: int = 15

    ai_provider: Literal["none", "anthropic"] = "none"
    ai_api_key: str | None = None
    ai_model: str = "claude-opus-5"
    embedding_provider: Literal["local", "openai_compatible"] = "local"
    embedding_api_url: str | None = None
    embedding_model: str | None = None
    vector_database_url: str | None = None

    email_provider: Literal["console", "smtp"] = "console"
    email_from: str = "no-reply@symbio.local"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None

    push_provider: Literal["none", "expo"] = "none"
    expo_access_token: str | None = None

    cors_origins: str = "http://localhost:5173,http://localhost:8081"
    jobs_mode: Literal["thread", "eager"] = "thread"
    rate_limit_enabled: bool = True

    seed_demo_password: str = "Symbio-Demo-2026!"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        # Heroku-style URLs use postgres://; SQLAlchemy needs an explicit driver.
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    @model_validator(mode="after")
    def _refuse_insecure_production(self) -> "Settings":
        if self.app_env == "production":
            if self.jwt_secret in _INSECURE_SECRETS or self.jwt_refresh_secret in _INSECURE_SECRETS:
                raise ValueError("JWT_SECRET and JWT_REFRESH_SECRET must be set to strong values in production")
            if self.jwt_secret == self.jwt_refresh_secret:
                raise ValueError("JWT_SECRET and JWT_REFRESH_SECRET must differ")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; use PostgreSQL")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()

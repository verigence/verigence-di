"""settings.py — Verigence DI application configuration.

All runtime configuration is read from environment variables.
No secrets live in source code. Uses pydantic-settings for
validation and type coercion at startup.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    PRODUCTION = "production"


class StorageProvider(str, Enum):
    MINIO = "minio"
    R2 = "r2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DI_",
        env_file=("infra/.env.local", "infra/.env.dev", "infra/.env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    env: Environment = Environment.LOCAL
    secret_key: str = Field(min_length=32)
    log_level: str = "INFO"

    # Database
    database_url: str  # postgresql+asyncpg://...

    # Storage
    storage_provider: StorageProvider = StorageProvider.MINIO
    storage_endpoint: str = "http://localhost:9000"
    storage_access_key_id: str = "minioadmin"
    storage_secret_access_key: str = "minioadmin123"
    storage_bucket: str = "verigence-di-dev"
    storage_region: str = "us-east-1"

    # Auth — Clerk
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""

    # Google Document AI
    docai_mock: bool = True  # True = use mock adapter (local/CI)
    docai_project_id: str = ""
    docai_location: str = "us"
    docai_processor_id: str = ""

    # Sentry
    sentry_dsn: str = ""

    # Derived helpers
    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION

    @field_validator("database_url")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """Ensure asyncpg driver prefix."""
        return (
            v.replace("postgresql://", "postgresql+asyncpg://")
            .replace("postgres://", "postgresql+asyncpg://")
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Use as FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]

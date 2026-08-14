"""settings.py — Verigence DI application configuration.

All runtime configuration is read from environment variables.
No secrets live in source code. Uses pydantic-settings for
validation and type coercion at startup.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
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

    # Auth — Security module
    security_jwks_url: str = ""  # https://<security-host>/.well-known/jwks.json

    # Azure Document Intelligence (D13 + D18)
    docai_mock: bool = True  # True = use mock adapter (local/CI)
    docai_azure_endpoint: str = ""   # https://<resource>.cognitiveservices.azure.com/
    docai_azure_key: str = ""        # API key from Azure portal → Keys and Endpoint

    # Sentry
    sentry_dsn: str = ""

    # Processing Worker
    worker_poll_interval_seconds: int = 5
    worker_enabled: bool = True
    worker_id: str = ""   # auto-generated from hostname+PID when empty

    # Verification threshold — system-wide default; per-tenant value in DB overrides this
    verification_threshold: float = 90.00

    # Derived helpers
    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION

    @model_validator(mode="after")
    def safety_rules(self) -> Settings:
        """Block unsafe configurations at startup — fail fast before serving traffic."""
        if self.is_production:
            # Real JWKS URL required in production
            if not self.security_jwks_url or "mock" in self.security_jwks_url.lower():
                raise ValueError(
                    "DI_SECURITY_JWKS_URL must be a real JWKS endpoint in production"
                )
            # Real Azure Document Intelligence required in production
            if not self.docai_mock and not self.docai_azure_endpoint:
                raise ValueError(
                    "DI_DOCAI_AZURE_ENDPOINT must be set when DI_DOCAI_MOCK=false in production"
                )
        return self

    @field_validator("database_url")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """Ensure asyncpg driver prefix and fix sslmode param for asyncpg."""
        v = (
            v.replace("postgresql://", "postgresql+asyncpg://")
            .replace("postgres://", "postgresql+asyncpg://")
        )
        # asyncpg does not accept ?sslmode=require — replace with ?ssl=require
        v = v.replace("?sslmode=require", "?ssl=require")
        v = v.replace("&sslmode=require", "&ssl=require")
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Use as FastAPI dependency."""
    return Settings()  # type: ignore[call-arg]

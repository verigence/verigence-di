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


class WorkerMode(str, Enum):
    """Runtime topology for the standalone DI worker process."""

    COMBINED = "combined"
    LEGACY = "legacy"
    V2 = "v2"


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

    # Logging — D27
    log_level: str = "INFO"           # DEBUG | INFO | WARNING | ERROR
    log_stdout: bool = True            # emit structured logs to stdout
    log_axiom: bool = False            # emit logs to Axiom (async, fire-and-forget)
    axiom_token: str = ""              # Axiom API token (required if log_axiom=true)
    axiom_dataset: str = "verigence-di"  # Axiom dataset name

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

    # Gemini 2.5 Flash — AI/OCR provider (D19, supersedes D13 Azure)
    docai_mock: bool = True          # True = use mock adapter (local/CI)
    docai_gemini_api_key: str = ""   # Google AI Studio API key

    # Sentry
    sentry_dsn: str = ""

    # Processing Worker
    # Default poll interval is 30s — used as fallback safety net only when
    # DI_WORKER_NOTIFY_DB_URL is set and pg_notify is active.
    # Set to 5s if running in poll-only mode (DI_WORKER_NOTIFY_DB_URL empty).
    worker_poll_interval_seconds: int = 30
    worker_enabled: bool = True
    worker_id: str = ""   # auto-generated from hostname+PID when empty
    # combined preserves the historical single-process topology for local/CI.
    # Railway DEV/PROD explicitly split legacy and V2 workloads into services.
    worker_mode: WorkerMode = WorkerMode.COMBINED
    # Bounded V2 pools. These are per process/replica and intentionally separate
    # from the legacy/V1 lane so V1 behaviour can remain sequential.
    v2_classification_concurrency: int = Field(default=6, ge=1, le=32)
    v2_extraction_concurrency: int = Field(default=4, ge=1, le=32)
    # Direct Neon endpoint URL for the dedicated LISTEN connection.
    # Must NOT use the PgBouncer pooler endpoint — LISTEN/NOTIFY requires a
    # persistent direct connection (Neon: ep-xxx.region.neon.tech, no -pooler.).
    # Empty string disables pg_notify and falls back to poll-only mode.
    worker_notify_db_url: str = ""

    # Backout queue TTL — failed jobs are written to backout_jobs and expire after this many hours (D24)
    backout_ttl_hours: int = 12

    # Worker lease timeout — RUNNING jobs older than this are reclaimed by the stale job reaper
    worker_lease_timeout_minutes: int = 10

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
            if not self.security_jwks_url or "mock" in self.security_jwks_url.lower():
                raise ValueError(
                    "DI_SECURITY_JWKS_URL must be a real JWKS endpoint in production"
                )
            if not self.docai_mock and not self.docai_gemini_api_key:
                raise ValueError(
                    "DI_DOCAI_GEMINI_API_KEY must be set when DI_DOCAI_MOCK=false in production"
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
        v = v.replace("?sslmode=require", "?ssl=require")
        v = v.replace("&sslmode=require", "&ssl=require")
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Use as FastAPI dependency."""
    return Settings()

"""tests/conftest.py — pytest fixtures shared across all tests.

Docker / PostgreSQL fixtures are gated behind a `needs_docker` marker so that
pure unit tests (marked `no_docker`) can run in CI without Docker Desktop.

Fixture dependency chain:
    pg_container  ← needs_docker
    db_url        ← pg_container
    apply_migrations (autouse, session) ← db_url
    db_session    ← db_url
    client        ← db_url

When every collected test is marked `no_docker`, the `pg_container` fixture
(and everything that depends on it) is never instantiated.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Env defaults needed before any app import ────────────────────────────────
os.environ.setdefault("DI_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("DI_DOCAI_MOCK", "true")
os.environ.setdefault("DI_STORAGE_PROVIDER", "minio")
os.environ.setdefault("DI_STORAGE_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("DI_STORAGE_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("DI_STORAGE_SECRET_ACCESS_KEY", "minioadmin123")
os.environ.setdefault("DI_STORAGE_BUCKET", "verigence-di-test")
os.environ.setdefault("DI_CLERK_PUBLISHABLE_KEY", "pk_test_mock")
os.environ.setdefault("DI_CLERK_SECRET_KEY", "sk_test_mock")
os.environ.setdefault("DI_CLERK_JWKS_URL", "http://localhost/mock-jwks")
# Provide a dummy DB URL so Settings validation doesn't fail for unit tests
os.environ.setdefault("DI_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")


# ── Marker registration ───────────────────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "no_docker: mark test as not requiring Docker/PostgreSQL container",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _needs_docker(config: pytest.Config) -> bool:
    """Return True when at least one collected test needs Docker (is NOT no_docker)."""
    # During collection, config.option may expose selected items via -k etc.
    # We use the lightest possible check: if *all* items in the current run
    # carry the no_docker marker then we can skip Docker entirely.
    # This check is evaluated lazily inside each fixture via request.config.
    return True  # Conservative default — override in _session_needs_docker below.


# ── Event loop (session-scoped for pytest-asyncio) ────────────────────────────

@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Docker-gated PostgreSQL fixtures ─────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_container(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    """Start a real PostgreSQL container for the entire test session.

    Skipped automatically when only `no_docker` tests are collected.
    """
    # If every test in this session carries no_docker, skip the container.
    items = request.session.items
    all_no_docker = all(
        item.get_closest_marker("no_docker") is not None for item in items
    )
    if all_no_docker:
        pytest.skip("All tests are marked no_docker; skipping PostgreSQL container.")

    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[import]
    except ImportError as exc:
        pytest.skip(f"testcontainers not installed: {exc}")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(pg_container) -> str:  # type: ignore[no-untyped-def]
    url = pg_container.get_connection_url()
    # Convert to asyncpg driver for the app; psycopg2 URL comes from testcontainers
    return (
        url.replace("psycopg2", "asyncpg")
        .replace("postgresql://", "postgresql+asyncpg://")
    )


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(request: pytest.FixtureRequest) -> None:
    """Run Alembic migrations once for the whole test session.

    Skipped for pure unit-test runs (all tests marked no_docker).
    """
    items = request.session.items
    all_no_docker = all(
        item.get_closest_marker("no_docker") is not None for item in items
    )
    if all_no_docker:
        return  # Nothing to migrate — no DB available.

    import subprocess

    # Resolve db_url via the fixture system
    url = cast(str, request.getfixturevalue("db_url"))
    env = os.environ.copy()
    env["DI_DATABASE_URL"] = url
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
    )


# ── Per-test DB session ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session(db_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield a test DB session that rolls back after each test."""
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# ── HTTP test client ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client wired to the FastAPI app."""
    os.environ["DI_DATABASE_URL"] = db_url
    # Clear settings cache so the new DB URL is picked up
    from verigence.di.settings import get_settings
    get_settings.cache_clear()

    from verigence.di.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

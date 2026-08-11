"""tests/conftest.py — pytest fixtures shared across all tests."""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer  # type: ignore[import]

# Point settings at the test DB before importing the app
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


@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def pg_container():
    """Start a real PostgreSQL container for the entire test session."""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(pg_container) -> str:  # type: ignore[no-untyped-def]
    url = pg_container.get_connection_url()
    # Convert to asyncpg driver
    return url.replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://")


@pytest.fixture(scope="session", autouse=True)
async def apply_migrations(db_url: str) -> None:  # type: ignore[misc]
    """Run Alembic migrations once for the whole test session."""
    import subprocess
    env = os.environ.copy()
    env["DI_DATABASE_URL"] = db_url
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
    )


@pytest_asyncio.fixture
async def db_session(db_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield a test DB session that rolls back after each test."""
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client wired to the FastAPI app."""
    os.environ["DI_DATABASE_URL"] = db_url
    from verigence.di.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

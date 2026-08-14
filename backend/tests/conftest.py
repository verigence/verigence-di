"""tests/conftest.py — pytest fixtures shared across all tests.

Docker / PostgreSQL fixtures are gated behind a `needs_docker` marker so that
pure unit tests (marked `no_docker`) can run in CI without Docker Desktop.

Smoke / Extended tests use ASGITransport + Neon DB + real R2 + real RSA JWTs.
The JWKS verification key is derived from TEST_JWT_PRIVATE_KEY in CI so the
signing and verification material cannot drift; local runs fall back to the
committed public test JWKS fixture.

Fixture dependency chain (unit tests):
    pg_container  ← needs_docker
    db_url        ← pg_container
    apply_migrations (autouse, session) ← db_url
    db_session    ← db_url
    client        ← db_url

Fixture dependency chain (smoke / extended):
    api_client    ← env overrides + JWKS patch
    test_tenant_id
    tenant_cleanup ← test_tenant_id + api_client
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# ── Env defaults needed before any app import ────────────────────────────────
os.environ.setdefault("DI_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("DI_DOCAI_MOCK", "true")
os.environ.setdefault("DI_STORAGE_PROVIDER", "minio")
os.environ.setdefault("DI_STORAGE_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("DI_STORAGE_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("DI_STORAGE_SECRET_ACCESS_KEY", "minioadmin123")
os.environ.setdefault("DI_STORAGE_BUCKET", "verigence-di-test")
os.environ.setdefault("DI_SECURITY_JWKS_URL", "http://localhost/mock-jwks")
# Provide a dummy DB URL so Settings validation doesn't fail for unit tests
os.environ.setdefault("DI_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

# ── JWKS fixture path ─────────────────────────────────────────────────────────
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TEST_JWKS_PATH = _FIXTURES_DIR / "test_jwks.json"
_TEST_KID = "verigence-di-test-key-1"


# ── Marker registration ───────────────────────────────────────────────────────
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "no_docker: mark test as not requiring Docker/PostgreSQL container",
    )
    config.addinivalue_line(
        "markers",
        "smoke: Tier 1 — fast integration tests, mandatory on every build, blocks deploy",
    )
    config.addinivalue_line(
        "markers",
        "extended: Tier 2 — comprehensive integration tests, triggered on demand",
    )
    config.addinivalue_line(
        "markers",
        "post_deploy_smoke: hits live Railway URL with real HTTP after deploy",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _needs_docker(config: pytest.Config) -> bool:
    """Return True when at least one collected test needs Docker (is NOT no_docker)."""
    return True  # Conservative default


def _async_db_url(url: str) -> str:
    """Normalize PostgreSQL URLs for SQLAlchemy's asyncpg engine."""
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break
    url = url.replace("?sslmode=require", "?ssl=require")
    return url.replace("&sslmode=require", "&ssl=require")


# ── Event loop (session-scoped for pytest-asyncio) ────────────────────────────
@pytest.fixture(scope="session")
def event_loop():  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── JWKS patch — session-scoped, used by smoke + extended tests ───────────────
def _load_test_jwks() -> dict:  # type: ignore[type-arg]
    """Load the committed test JWKS file."""
    with _TEST_JWKS_PATH.open() as f:
        return json.load(f)


def _make_jwks_get_key(jwks_data: dict):  # type: ignore[type-arg]
    """Return a get_key function that serves keys from committed test JWKS."""
    from jose import jwk  # type: ignore[import]

    key_map = {}
    for key_data in jwks_data.get("keys", []):
        kid = key_data.get("kid", "")
        key_map[kid] = jwk.construct(key_data)

    def get_key(kid: str):  # type: ignore[return]
        return key_map.get(kid)

    return get_key


def _make_ci_private_key_get_key(private_key_b64: str):  # type: ignore[no-untyped-def]
    """Verify CI JWTs with the exact private key used to sign them.

    The private key never leaves process memory. python-jose's RSA key object can
    verify signatures using private-key material, which removes stale public-JWKS
    fixture risk while preserving real RS256 verification in smoke tests.
    """
    from jose import jwk  # type: ignore[import]

    key = jwk.construct(base64.b64decode(private_key_b64), algorithm="RS256")

    def get_key(kid: str):  # type: ignore[return]
        return key if kid == _TEST_KID else None

    return get_key


@pytest.fixture(scope="session", autouse=False)
def _patch_jwks_cache():
    """Patch JWKSCache.get_key for deterministic smoke/extended JWT verification."""
    private_key_b64 = os.environ.get("TEST_JWT_PRIVATE_KEY", "")
    if private_key_b64:
        get_key_fn = _make_ci_private_key_get_key(private_key_b64)
    else:
        get_key_fn = _make_jwks_get_key(_load_test_jwks())

    with patch("verigence.di.auth.jwks.JWKSCache.get_key", side_effect=get_key_fn):
        yield


# ── Docker-gated PostgreSQL fixtures ─────────────────────────────────────────
@pytest.fixture(scope="session")
def pg_container(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    """Start a real PostgreSQL container for the entire test session.

    Skipped automatically when only `no_docker` tests are collected.
    """
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
    return _async_db_url(pg_container.get_connection_url())


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
        return

    import subprocess

    url = cast("str", request.getfixturevalue("db_url"))
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


# ── HTTP test client (unit tests) ─────────────────────────────────────────────
@pytest_asyncio.fixture
async def client(db_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client wired to the FastAPI app (unit/docker tests)."""
    os.environ["DI_DATABASE_URL"] = db_url
    from verigence.di.settings import get_settings
    get_settings.cache_clear()

    from verigence.di.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Integration test fixtures (smoke + extended) ─────────────────────────────
@pytest.fixture
def test_tenant_id() -> str:
    """Return a unique tenant ID for each test (format: test-<8 hex chars>)."""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def api_client(_patch_jwks_cache) -> AsyncGenerator[AsyncClient, None]:  # type: ignore[no-untyped-def]
    """AsyncClient over ASGITransport wired to Neon DB + real R2 + real JWTs.

    A fresh NullPool engine/session factory is bound for each test event loop so
    asyncpg connections are never reused across pytest-asyncio loops.
    """
    neon_url = os.environ.get("DI_DATABASE_URL", "")
    if not neon_url or "localhost" in neon_url:
        pytest.skip("Neon DI_DATABASE_URL not set — skipping integration test")

    env_overrides = {
        "DI_DATABASE_URL": neon_url,
        "DI_ENV": "dev",
        "DI_DOCAI_MOCK": "true",
        "DI_WORKER_ENABLED": "false",
        "DI_STORAGE_PROVIDER": os.environ.get("DI_STORAGE_PROVIDER", "minio"),
        "DI_STORAGE_BUCKET": os.environ.get("DI_STORAGE_BUCKET", "verigence-di-test"),
        "DI_STORAGE_ENDPOINT": os.environ.get("DI_STORAGE_ENDPOINT", "http://localhost:9000"),
        "DI_STORAGE_ACCESS_KEY_ID": os.environ.get("DI_STORAGE_ACCESS_KEY_ID", "minioadmin"),
        "DI_STORAGE_SECRET_ACCESS_KEY": os.environ.get("DI_STORAGE_SECRET_ACCESS_KEY", "minioadmin123"),
        "DI_STORAGE_REGION": os.environ.get("DI_STORAGE_REGION", "us-east-1"),
    }

    original = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    from verigence.di.settings import get_settings
    get_settings.cache_clear()

    import verigence.di.repositories.database as _db_mod
    old_engine = _db_mod._engine
    with contextlib.suppress(Exception):
        await old_engine.dispose()

    test_engine = create_async_engine(
        _async_db_url(neon_url),
        poolclass=NullPool,
        echo=False,
    )
    _db_mod._engine = test_engine
    _db_mod.AsyncSessionFactory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    from verigence.di.main import create_app
    app = create_app()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        await test_engine.dispose()
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def tenant_cleanup(test_tenant_id: str) -> AsyncGenerator[None, None]:
    """Delete all DB rows for test_tenant_id after each integration test."""
    yield

    neon_url = os.environ.get("DI_DATABASE_URL", "")
    if not neon_url or "localhost" in neon_url:
        return

    engine = create_async_engine(_async_db_url(neon_url), echo=False, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            sql = __import__("sqlalchemy", fromlist=["text"]).text
            # tenant_settings and retention_policies form a deliberate FK cycle:
            # retention_policies.tenant_id -> tenant_settings and
            # tenant_settings.active_retention_policy_id -> retention_policies.
            # Clear the active pointer before deleting either side.
            await conn.execute(
                sql(
                    "UPDATE docintel.tenant_settings "
                    "SET active_retention_policy_id = NULL WHERE tenant_id = :tid"
                ),
                {"tid": test_tenant_id},
            )
            for table in [
                "docintel.processing_jobs",
                "docintel.document_artifacts",
                "docintel.documents",
                "docintel.subjects",
                "docintel.tenant_document_types",
                "docintel.actors",
                "docintel.retention_policies",
                "docintel.tenant_settings",
            ]:
                await conn.execute(
                    sql(f"DELETE FROM {table} WHERE tenant_id = :tid"),  # noqa: S608
                    {"tid": test_tenant_id},
                )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def storage_cleanup(test_tenant_id: str) -> AsyncGenerator[None, None]:
    """Delete all R2 test objects with key prefix matching test_tenant_id."""
    yield

    storage_provider = os.environ.get("DI_STORAGE_PROVIDER", "minio")
    if storage_provider not in ("r2", "minio"):
        return

    try:
        from verigence.di.settings import get_settings
        from verigence.di.storage.adapter import get_storage_adapter

        settings = get_settings()
        adapter = get_storage_adapter(settings)
        prefix = f"{test_tenant_id}/"

        # List and delete objects — best-effort cleanup, swallow errors
        import aioboto3  # type: ignore[import]
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
            region_name=settings.storage_region,
        ) as s3:
            resp = await s3.list_objects_v2(
                Bucket=settings.storage_bucket, Prefix=prefix
            )
            objects = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            if objects:
                await s3.delete_objects(
                    Bucket=settings.storage_bucket,
                    Delete={"Objects": objects},
                )
    except Exception:  # noqa: BLE001
        pass  # cleanup is best-effort

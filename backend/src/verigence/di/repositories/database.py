"""database.py — async SQLAlchemy engine, session factory and RLS helper.

Every request/worker transaction must call set_tenant_context() before
any query so that PostgreSQL RLS policies (app.tenant_id) are enforced.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from verigence.di.settings import get_settings


# ── Engine (module singleton) ─────────────────────────────────────────────────
def _make_engine():  # type: ignore[no-untyped-def]
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=not settings.is_production,
    )


_engine = _make_engine()

AsyncSessionFactory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ── RLS tenant context ────────────────────────────────────────────────────────
async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set transaction-local tenant_id for PostgreSQL RLS.

    Must be called at the start of every tenant-scoped transaction.
    Uses SET LOCAL so the value is cleared automatically at transaction end.
    PostgreSQL SET LOCAL does not accept bind parameters — value is
    sanitised and interpolated directly.
    """
    # Strip any characters that are not alphanumeric, hyphen, or underscore
    # to prevent SQL injection via tenant_id.
    safe_tid = "".join(c for c in str(tenant_id) if c.isalnum() or c in "-_")
    await session.execute(text(f"SET LOCAL app.tenant_id = '{safe_tid}'"))


def get_engine():  # type: ignore[no-untyped-def]
    """Return the module-level engine (for non-FastAPI use in workers/schedulers)."""
    return _engine


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession; rolls back on exception, closes on exit."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Context manager for worker/scheduler use ─────────────────────────────────
@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Open a session, set RLS context, auto-provision tenant, and yield."""
    from verigence.di.repositories.tenants import (  # noqa: PLC0415
        provision_retention_policy,
        provision_tenant,
    )
    async with AsyncSessionFactory() as session:
        try:
            await set_tenant_context(session, tenant_id)
            await provision_tenant(session, tenant_id)
            await provision_retention_policy(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

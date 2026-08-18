"""health.py — /health/live and /health/ready endpoints.

/health/live  — liveness probe: always 200 if process is running (used by Railway)
/health/ready — readiness probe: 200 when DB reachable, 503 otherwise (used by Railway healthcheck)
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from verigence.di.repositories.database import AsyncSessionFactory
from verigence.di.settings import get_settings

router = APIRouter(tags=["Health"])


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    """Liveness probe — returns 200 if process is running."""
    return {"status": "live"}


@router.get("/health/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    """Readiness probe — checks DB connectivity. Returns 503 if not ready."""
    settings = get_settings()
    db_ready = False
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        db_ready = True
    except Exception:
        db_ready = False

    ready_now = db_ready
    return JSONResponse(
        status_code=200 if ready_now else 503,
        content={
            "status": "ready" if ready_now else "not_ready",
            "environment": settings.env.value,
            "databaseReady": db_ready,
        },
    )


# Keep backward-compatible aliases so existing Railway healthcheckPath=/health still works
@router.get("/health", include_in_schema=False)
async def health_legacy() -> dict[str, str]:
    """Legacy liveness alias — kept for backward compatibility."""
    return {"status": "ok"}


@router.get("/ready", include_in_schema=False)
async def ready_legacy() -> JSONResponse:
    """Legacy readiness alias — kept for backward compatibility."""
    return await ready()

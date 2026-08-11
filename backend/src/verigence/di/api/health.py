"""health.py — /health and /ready endpoints.

/health  — always returns 200 if the process is alive (used by Railway)
/ready   — checks DB connectivity (used by load balancer / smoke tests)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.repositories.database import get_db_session

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    version: str = "2.1.0"


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health() -> HealthResponse:
    """Liveness probe — returns 200 if process is running."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, include_in_schema=False)
async def ready(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    """Readiness probe — confirms DB is reachable."""
    await session.execute(text("SELECT 1"))
    return HealthResponse(status="ready")

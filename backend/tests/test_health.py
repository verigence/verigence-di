"""tests/test_health.py — Smoke tests for /health and /ready endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_correlation_id_header(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert "x-correlation-id" in response.headers


@pytest.mark.asyncio
async def test_health_accepts_caller_correlation_id(client: AsyncClient) -> None:
    cid = "test-run-001"
    response = await client.get("/health", headers={"X-Correlation-ID": cid})
    assert response.headers.get("x-correlation-id") == cid


@pytest.mark.asyncio
async def test_ready_endpoint(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

"""Post-deploy smoke tests for the live DI Railway service.

This suite proves deployment/runtime health only. It deliberately does NOT mint
an arbitrary test-key JWT and present it to live DI: deployed DI trusts the
Verigence Security JWKS, so positive authorization must use a real
Security-issued JWT. That cross-service proof belongs to Increment J.
"""
from __future__ import annotations

import os

import httpx
import pytest
import pytest_asyncio

_RAILWAY_URL = os.environ.get("RAILWAY_API_URL", "").rstrip("/")
_SMOKE_TENANT = os.environ.get("SMOKE_TENANT_ID", "post-deploy-smoke-tenant")


def _skip_if_no_railway() -> None:
    if not _RAILWAY_URL:
        pytest.skip("RAILWAY_API_URL not set — skipping post-deploy smoke")


@pytest_asyncio.fixture
async def live_client() -> httpx.AsyncClient:  # type: ignore[misc]
    """Create one HTTP client per test/event loop."""
    _skip_if_no_railway()
    async with httpx.AsyncClient(base_url=_RAILWAY_URL, timeout=15.0) as client:
        yield client


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_health_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json().get("status") == "live"


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_ready_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ready"


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_unauthenticated_rejected_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get(f"/v1/tenants/{_SMOKE_TENANT}/subjects")
    assert resp.status_code == 401


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_invalid_token_rejected_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get(
        f"/v1/tenants/{_SMOKE_TENANT}/subjects",
        headers={"Authorization": "Bearer garbage-token"},
    )
    assert resp.status_code == 401


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_correlation_id_present_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get("/health/live")
    assert "x-correlation-id" in resp.headers


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_correlation_id_echoed_live(live_client: httpx.AsyncClient) -> None:
    correlation_id = "post-deploy-smoke-correlation"
    resp = await live_client.get(
        "/health/live",
        headers={"X-Correlation-ID": correlation_id},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-correlation-id") == correlation_id

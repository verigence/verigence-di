"""tests/post_deploy/test_post_deploy_smoke.py — Post-deploy smoke tests.

Markers: pytest.mark.post_deploy_smoke
Infrastructure: real HTTP to live Railway URL using real RS256-signed JWTs

These tests run AFTER Railway deploys both services. They catch failures that
only manifest on real infrastructure: bad env vars, startup crashes, DB
connection failures, misconfigured CORS, etc.

Required env vars:
    RAILWAY_API_URL       — e.g. https://verigence-di-production.up.railway.app
    TEST_JWT_PRIVATE_KEY  — base64-encoded RSA private PEM
    SMOKE_TENANT_ID       — tenant used for post-deploy tests (default: post-deploy-smoke-tenant)
"""
from __future__ import annotations

import os

# Import jwt_helper via sys.path adjustment
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

# Allow importing from backend/tests when running from the backend directory
_tests_dir = Path(__file__).parent.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from jwt_helper import mint_jwt  # noqa: E402

_RAILWAY_URL = os.environ.get("RAILWAY_API_URL", "").rstrip("/")
_SMOKE_TENANT = os.environ.get("SMOKE_TENANT_ID", "post-deploy-smoke-tenant")


def _skip_if_no_railway() -> None:
    if not _RAILWAY_URL:
        pytest.skip("RAILWAY_API_URL not set — skipping post-deploy smoke")


def _admin_token() -> str:
    return mint_jwt(
        tenant_id=_SMOKE_TENANT,
        actor_id="post-deploy-smoke-actor",
        roles=["TENANT_ADMIN"],
    )


@pytest_asyncio.fixture(scope="module")
async def live_client() -> httpx.AsyncClient:  # type: ignore[misc]
    _skip_if_no_railway()
    async with httpx.AsyncClient(base_url=_RAILWAY_URL, timeout=15.0) as client:
        yield client


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_health_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_ready_live(live_client: httpx.AsyncClient) -> None:
    resp = await live_client.get("/health/ready")
    assert resp.status_code in (200, 503)  # 503 acceptable if DB unavailable


# ── Auth ──────────────────────────────────────────────────────────────────────

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
async def test_authenticated_list_subjects_live(live_client: httpx.AsyncClient) -> None:
    token = _admin_token()
    resp = await live_client.get(
        f"/v1/tenants/{_SMOKE_TENANT}/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_wrong_tenant_rejected_live(live_client: httpx.AsyncClient) -> None:
    """Valid JWT for SMOKE_TENANT against a different tenant path → 403."""
    token = _admin_token()
    resp = await live_client.get(
        "/v1/tenants/completely-different-tenant/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_create_subject_live(live_client: httpx.AsyncClient) -> None:
    """Create a subject on the live service — verifies DB is reachable."""
    token = _admin_token()
    resp = await live_client.post(
        f"/v1/tenants/{_SMOKE_TENANT}/subjects",
        headers={"Authorization": f"Bearer {token}"},
        json={"externalRef": "POST-DEPLOY-SMOKE-001", "displayName": "Post Deploy Smoke Test"},
    )
    assert resp.status_code in (201, 409)  # 409 if already exists from a previous run


@pytest.mark.post_deploy_smoke
@pytest.mark.asyncio
async def test_correlation_id_present_live(live_client: httpx.AsyncClient) -> None:
    """Every response must include X-Correlation-ID header."""
    resp = await live_client.get("/health/live")
    assert "x-correlation-id" in resp.headers

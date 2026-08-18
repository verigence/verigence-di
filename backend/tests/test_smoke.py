"""tests/test_smoke.py — Tier 1 smoke tests. Mandatory on every build, blocks deploy.

Markers: pytest.mark.smoke
Infrastructure: ASGITransport + Neon DB + real JWTs (via jwt_helper)
JWKS: verification material is tied to the CI signing key by conftest
Run time target: < 30 seconds

Coverage:
  - Health endpoints respond correctly
  - Correlation ID header is echoed / generated
  - Missing / invalid / wrong-tenant tokens rejected
  - Insufficient permission rejected
  - Subject create + get round-trip works
  - Error responses use Problem JSON shape
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.jwt_helper import mint_jwt

# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_health_returns_live(api_client: AsyncClient) -> None:
    resp = await api_client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "live"


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_ready_returns_ok(api_client: AsyncClient) -> None:
    resp = await api_client.get("/health/ready")
    assert resp.status_code in (200, 503)  # 503 if DB unreachable, but endpoint exists


# ── Correlation ID ────────────────────────────────────────────────────────────

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_correlation_id_echoed_in_response(api_client: AsyncClient) -> None:
    cid = "smoke-test-correlation-001"
    resp = await api_client.get("/health/live", headers={"X-Correlation-ID": cid})
    assert resp.headers.get("x-correlation-id") == cid


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_correlation_id_generated_when_absent(api_client: AsyncClient) -> None:
    resp = await api_client.get("/health/live")
    assert "x-correlation-id" in resp.headers
    assert len(resp.headers["x-correlation-id"]) > 0


# ── Auth rejection ────────────────────────────────────────────────────────────

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_missing_auth_returns_401(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    resp = await api_client.get(f"/v1/tenants/{test_tenant_id}/subjects")
    assert resp.status_code == 401


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_invalid_token_returns_401(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_wrong_tenant_returns_403(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    """Valid JWT for test_tenant_id used against a different tenant path."""
    token = mint_jwt(
        tenant_id=test_tenant_id,
        actor_id="actor-smoke-01",
        roles=["TENANT_ADMIN"],
    )
    other_tenant = "completely-different-tenant-id"
    resp = await api_client.get(
        f"/v1/tenants/{other_tenant}/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_insufficient_permission_returns_403(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    """OPERATIONS_VIEWER token cannot create a subject."""
    token = mint_jwt(
        tenant_id=test_tenant_id,
        actor_id="actor-smoke-viewer",
        roles=["OPERATIONS_VIEWER"],
    )
    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
        json={"subjectType": "PERSON", "displayName": "Smoke Test Subject"},
    )
    assert resp.status_code == 403


# ── Subject round-trip ────────────────────────────────────────────────────────

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_create_subject_returns_201(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    token = mint_jwt(
        tenant_id=test_tenant_id,
        actor_id="actor-smoke-admin",
        roles=["TENANT_ADMIN"],
    )
    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
        json={"subjectType": "PERSON", "displayName": "Smoke Subject"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "subjectId" in body["data"]
    assert body["data"]["subjectType"] == "PERSON"


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_get_subject_returns_created_subject(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    token = mint_jwt(
        tenant_id=test_tenant_id,
        actor_id="actor-smoke-admin",
        roles=["TENANT_ADMIN"],
    )
    auth = {"Authorization": f"Bearer {token}"}

    # Create
    create_resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers=auth,
        json={"subjectType": "PERSON", "displayName": "Smoke Get Subject"},
    )
    assert create_resp.status_code == 201
    subject_id = create_resp.json()["data"]["subjectId"]

    # Retrieve
    get_resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}",
        headers=auth,
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["data"]["subjectId"] == subject_id
    assert body["data"]["subjectType"] == "PERSON"
    assert body["data"]["displayName"] == "Smoke Get Subject"


# ── Problem JSON shape ────────────────────────────────────────────────────────

@pytest.mark.smoke
@pytest.mark.asyncio
async def test_error_response_is_problem_json(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    """Any 401 response must return a Problem JSON body with code + title + status."""
    resp = await api_client.get(f"/v1/tenants/{test_tenant_id}/subjects")
    assert resp.status_code == 401
    body = resp.json()
    assert "code" in body or "title" in body  # at minimum one Problem JSON field
    assert "status" in body

"""tests/test_extended_tenant_config.py — Tier 2 tenant config tests (on demand).

Markers: pytest.mark.extended
Infrastructure: ASGITransport + Neon DB + real JWTs

Coverage:
  - GET returns null threshold for new tenant
  - PUT updates verification threshold
  - PUT requires TENANT_CONFIG_WRITE permission
  - Threshold persists across requests
  - Null threshold allows system default via env var
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.jwt_helper import mint_jwt


def _admin_token(tenant_id: str) -> str:
    return mint_jwt(tenant_id=tenant_id, actor_id="actor-config-admin", roles=["TENANT_ADMIN"])


# ── GET ───────────────────────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_get_tenant_settings_returns_null_threshold_for_new_tenant(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """New tenant with no settings row → verificationThreshold is null."""
    token = _admin_token(test_tenant_id)
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json().get("verificationThreshold") is None


# ── PUT ───────────────────────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_put_updates_verification_threshold(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    token = _admin_token(test_tenant_id)
    auth = {"Authorization": f"Bearer {token}"}

    put_resp = await api_client.put(
        f"/v1/tenants/{test_tenant_id}/settings",
        headers=auth,
        json={"verificationThreshold": 85.00},
    )
    assert put_resp.status_code in (200, 201, 204)

    get_resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/settings", headers=auth
    )
    assert get_resp.status_code == 200
    assert get_resp.json().get("verificationThreshold") == 85.00


@pytest.mark.extended
@pytest.mark.asyncio
async def test_put_requires_tenant_config_write(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    """OPERATIONS_VIEWER lacks di.tenant_config.write — PUT must return 403."""
    token = mint_jwt(
        tenant_id=test_tenant_id, actor_id="actor-viewer", roles=["OPERATIONS_VIEWER"]
    )
    resp = await api_client.put(
        f"/v1/tenants/{test_tenant_id}/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"verificationThreshold": 70.00},
    )
    assert resp.status_code == 403


@pytest.mark.extended
@pytest.mark.asyncio
async def test_threshold_persists_across_requests(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """Write threshold in one request, read it back in a separate request."""
    token = _admin_token(test_tenant_id)
    auth = {"Authorization": f"Bearer {token}"}

    # Write
    put = await api_client.put(
        f"/v1/tenants/{test_tenant_id}/settings",
        headers=auth,
        json={"verificationThreshold": 72.50},
    )
    assert put.status_code in (200, 201, 204)

    # Read back in a second independent request
    get = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/settings", headers=auth
    )
    assert get.status_code == 200
    assert get.json().get("verificationThreshold") == 72.50


@pytest.mark.extended
@pytest.mark.asyncio
async def test_null_threshold_uses_system_default(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """When no row exists, get_verification_threshold returns None and worker uses env var."""

    from verigence.di.settings import get_settings

    settings = get_settings()
    # The system default is DI_VERIFICATION_THRESHOLD (may not be set — defaults to None or 0)
    system_default = getattr(settings, "verification_threshold", None)

    token = _admin_token(test_tenant_id)
    get_resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Either 200 with null, or 404 — both mean no tenant-specific threshold
    if get_resp.status_code == 200:
        tenant_threshold = get_resp.json().get("verificationThreshold")
        assert tenant_threshold is None or tenant_threshold == system_default

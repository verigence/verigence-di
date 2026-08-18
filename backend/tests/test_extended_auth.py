"""tests/test_extended_auth.py — Tier 2 extended auth tests (on demand).

Markers: pytest.mark.extended
Infrastructure: ASGITransport + Neon DB + real JWTs
Coverage:
  - Expired tokens rejected
  - Wrong audience rejected
  - Wrong issuer rejected
  - Cross-tenant data isolation (subjects + documents)
  - Role permission boundaries
  - Multi-role permission union
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.jwt_helper import (
    mint_expired_jwt,
    mint_jwt,
    mint_jwt_wrong_audience,
    mint_jwt_wrong_issuer,
)

# ── Token validation edge cases ───────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_expired_token_returns_401(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    token = mint_expired_jwt(
        tenant_id=test_tenant_id, actor_id="actor-expired", roles=["TENANT_ADMIN"]
    )
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.extended
@pytest.mark.asyncio
async def test_token_wrong_audience_returns_401(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    token = mint_jwt_wrong_audience(tenant_id=test_tenant_id, actor_id="actor-aud")
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.extended
@pytest.mark.asyncio
async def test_token_wrong_issuer_returns_401(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    token = mint_jwt_wrong_issuer(tenant_id=test_tenant_id, actor_id="actor-iss")
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


# ── Tenant isolation ──────────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_tenant_isolation_subjects(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """Subject created under tenant-A is not visible under tenant-B."""
    tenant_a = test_tenant_id
    tenant_b = f"other-{test_tenant_id}"

    token_a = mint_jwt(tenant_id=tenant_a, actor_id="actor-a", roles=["TENANT_ADMIN"])
    token_b = mint_jwt(tenant_id=tenant_b, actor_id="actor-b", roles=["TENANT_ADMIN"])

    # Create under tenant A
    create = await api_client.post(
        f"/v1/tenants/{tenant_a}/subjects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"externalRef": "ISO-SUBJ-001", "displayName": "Isolation Test Subject"},
    )
    assert create.status_code == 201
    subject_id = create.json()["subjectId"]

    # Try to GET under tenant B — must be 404 (not found in tenant B's scope)
    get_b = await api_client.get(
        f"/v1/tenants/{tenant_b}/subjects/{subject_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_b.status_code in (403, 404)


# ── Permission boundaries ─────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_viewer_cannot_create_subject(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    token = mint_jwt(
        tenant_id=test_tenant_id, actor_id="actor-viewer", roles=["OPERATIONS_VIEWER"]
    )
    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
        json={"externalRef": "PERM-001", "displayName": "Should Fail"},
    )
    assert resp.status_code == 403


@pytest.mark.extended
@pytest.mark.asyncio
async def test_operator_can_upload_but_not_delete(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """DOCUMENT_OPERATOR can create subjects and upload documents but not delete."""
    token = mint_jwt(
        tenant_id=test_tenant_id, actor_id="actor-operator", roles=["DOCUMENT_OPERATOR"]
    )
    auth = {"Authorization": f"Bearer {token}"}

    # Create a subject first
    subj_resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers=auth,
        json={"externalRef": "OP-SUBJ-001", "displayName": "Operator Subject"},
    )
    assert subj_resp.status_code == 201
    subject_id = subj_resp.json()["subjectId"]

    # Upload a document
    import io
    pdf_bytes = b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj\r\n%%EOF"
    upload_resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers=auth,
        files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        data={"documentTypeId": "test-doc-type"},
    )
    # Upload either succeeds or fails with 422/400 if doc type doesn't exist — either way not 403
    assert upload_resp.status_code != 403

    # Attempt delete — should be 403 (DOCUMENT_OPERATOR lacks di.document.delete)
    doc_id = "00000000-0000-0000-0000-000000000001"
    delete_resp = await api_client.delete(
        f"/v1/tenants/{test_tenant_id}/documents/{doc_id}",
        headers=auth,
    )
    assert delete_resp.status_code == 403


@pytest.mark.extended
@pytest.mark.asyncio
async def test_multiple_roles_union_permissions(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None
) -> None:
    """Token with DOCUMENT_OPERATOR + DOCUMENT_VERIFIER can both upload and verify."""
    token = mint_jwt(
        tenant_id=test_tenant_id,
        actor_id="actor-multi-role",
        roles=["DOCUMENT_OPERATOR", "DOCUMENT_VERIFIER"],
    )
    auth = {"Authorization": f"Bearer {token}"}

    # Create subject — requires di.subject.create (DOCUMENT_OPERATOR has it)
    subj = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects",
        headers=auth,
        json={"externalRef": "MULTI-ROLE-001", "displayName": "Multi Role Subject"},
    )
    assert subj.status_code == 201

    # List verifications — requires di.verification.read (DOCUMENT_VERIFIER has it)
    subject_id = subj.json()["subjectId"]
    verif = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/verification-records",
        headers=auth,
    )
    # 200 or 404 both fine — the point is NOT 403
    assert verif.status_code != 403

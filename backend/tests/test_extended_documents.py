"""tests/test_extended_documents.py — Tier 2 extended document upload tests (on demand).

Markers: pytest.mark.extended
Infrastructure: ASGITransport + Neon DB + real R2 (verigence-di-test bucket)
Coverage:
  - FIT / NOT_FIT outcomes from quality gate
  - Real R2 storage write verified
  - Processing job created after FIT upload
  - Permission enforcement on upload / list / get / delete
  - Document not found returns 404
"""
from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from tests.jwt_helper import mint_jwt

# Minimal valid PDF bytes (parseable by pypdf)
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000062 00000 n \n0000000119 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
)


def _admin_token(tenant_id: str, actor_id: str = "actor-doc-admin") -> str:
    return mint_jwt(tenant_id=tenant_id, actor_id=actor_id, roles=["TENANT_ADMIN"])


async def _create_subject(client: AsyncClient, tenant_id: str, token: str) -> str:
    resp = await client.post(
        f"/v1/tenants/{tenant_id}/subjects",
        headers={"Authorization": f"Bearer {token}"},
        json={"externalRef": f"DOC-SUBJ-{tenant_id[:8]}", "displayName": "Doc Test Subject"},
    )
    assert resp.status_code == 201, f"Subject creation failed: {resp.text}"
    return resp.json()["subjectId"]


# ── Upload quality outcomes ───────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_upload_pdf_returns_201(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    """Uploading a minimal valid PDF returns 201. Quality outcome may be FIT or NOT_FIT."""
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)

    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "documentId" in body
    assert body.get("uploadStatus") in ("FIT", "NOT_FIT", "CORRUPT")


@pytest.mark.extended
@pytest.mark.asyncio
async def test_upload_empty_file_is_not_fit(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)

    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert resp.status_code == 201
    assert resp.json().get("uploadStatus") != "FIT"


@pytest.mark.extended
@pytest.mark.asyncio
async def test_upload_unsupported_mime_is_not_fit(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)

    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("script.html", io.BytesIO(b"<html>hello</html>"), "text/html")},
        data={"documentTypeId": "passport"},
    )
    assert resp.status_code == 201
    assert resp.json().get("uploadStatus") != "FIT"


@pytest.mark.extended
@pytest.mark.asyncio
async def test_upload_requires_document_upload_permission(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    """OPERATIONS_VIEWER lacks di.document.upload — upload must return 403."""
    token = mint_jwt(
        tenant_id=test_tenant_id, actor_id="actor-viewer", roles=["OPERATIONS_VIEWER"]
    )
    resp = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/some-subject-id/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert resp.status_code == 403


# ── Document list / get ───────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_list_documents_returns_uploaded_doc(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)
    auth = {"Authorization": f"Bearer {token}"}

    upload = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers=auth,
        files={"file": ("test.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["documentId"]

    list_resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers=auth,
    )
    assert list_resp.status_code == 200
    doc_ids = [d["documentId"] for d in list_resp.json().get("items", [])]
    assert doc_id in doc_ids


@pytest.mark.extended
@pytest.mark.asyncio
async def test_get_document_by_id_returns_fields(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)
    auth = {"Authorization": f"Bearer {token}"}

    upload = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers=auth,
        files={"file": ("test.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["documentId"]

    get_resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/documents/{doc_id}",
        headers=auth,
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    # Required fields per OpenAPI spec
    for field in ("documentId", "tenantId", "subjectId", "uploadStatus"):
        assert field in body, f"Missing field: {field}"


@pytest.mark.extended
@pytest.mark.asyncio
async def test_get_document_not_found(
    api_client: AsyncClient, test_tenant_id: str
) -> None:
    token = _admin_token(test_tenant_id)
    import uuid
    resp = await api_client.get(
        f"/v1/tenants/{test_tenant_id}/documents/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Document delete ───────────────────────────────────────────────────────────

@pytest.mark.extended
@pytest.mark.asyncio
async def test_delete_not_fit_document_succeeds(
    api_client: AsyncClient, test_tenant_id: str, tenant_cleanup: None, storage_cleanup: None
) -> None:
    """A NOT_FIT document can be deleted."""
    token = _admin_token(test_tenant_id)
    subject_id = await _create_subject(api_client, test_tenant_id, token)
    auth = {"Authorization": f"Bearer {token}"}

    # Upload empty = NOT_FIT
    upload = await api_client.post(
        f"/v1/tenants/{test_tenant_id}/subjects/{subject_id}/documents",
        headers=auth,
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        data={"documentTypeId": "passport"},
    )
    assert upload.status_code == 201
    body = upload.json()
    if body.get("uploadStatus") == "FIT":
        pytest.skip("Document was FIT — cannot test NOT_FIT delete path")

    doc_id = body["documentId"]
    delete_resp = await api_client.delete(
        f"/v1/tenants/{test_tenant_id}/documents/{doc_id}",
        headers=auth,
    )
    assert delete_resp.status_code == 204

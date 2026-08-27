from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from verigence.di.api.v1.pc_booking_documents import (
    PcBookingDocumentContentAccess,
    get_pc_booking_document_content_access,
)
from verigence.di.storage import download_access

pytestmark = pytest.mark.no_docker


def test_pc_booking_content_access_contract_is_url_only() -> None:
    fields = set(PcBookingDocumentContentAccess.model_fields)
    assert fields == {"documentId", "url", "mimeType", "expiresInSeconds"}
    assert "blob" not in fields
    assert "content" not in fields


def test_pc_booking_content_access_does_not_proxy_document_bytes() -> None:
    source = inspect.getsource(get_pc_booking_document_content_access)
    assert "create_presigned_download_url" in source
    assert "_document_content_response" not in source
    assert 'require_live_tenant_permission("di.document.content.read")' in source


def test_presigned_download_uses_private_bucket_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def generate_presigned_url(
            self,
            operation: str,
            *,
            Params: dict[str, str],
            ExpiresIn: int,
        ) -> str:
            captured.update(operation=operation, params=Params, expires=ExpiresIn)
            return "https://private-r2.example/document?signature=test"

    monkeypatch.setattr(download_access, "_presign_client", lambda: FakeClient())
    monkeypatch.setattr(
        download_access,
        "get_settings",
        lambda: SimpleNamespace(storage_bucket="verigence-private-documents"),
    )

    url = download_access.create_presigned_download_url(
        "tenant/subjects/customer/documents/booking.pdf",
        expires_seconds=600,
    )

    assert url.startswith("https://private-r2.example/")
    assert captured == {
        "operation": "get_object",
        "params": {
            "Bucket": "verigence-private-documents",
            "Key": "tenant/subjects/customer/documents/booking.pdf",
        },
        "expires": 600,
    }


def test_presigned_download_rejects_invalid_expiry() -> None:
    with pytest.raises(ValueError, match="between 1 and 3600"):
        download_access.create_presigned_download_url("document.pdf", expires_seconds=0)

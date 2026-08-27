from __future__ import annotations

import inspect

import pytest

from verigence.di.api.v1.pc_booking_documents import (
    PC_BOOKING_CONTENT_URL_TTL_SECONDS,
    PcBookingContentAccess,
    PcBookingDocumentStatus,
    PcBookingExtractionField,
    PcBookingUploadData,
    get_pc_booking_document_content_url,
    get_pc_booking_extraction_review,
    list_pc_booking_documents,
    upload_pc_booking_document,
)
from verigence.di.application.intake import intake_document
from verigence.di.repositories.audit_links import audit_link_retry_delay_seconds
from verigence.di.repositories.documents import get_document
from verigence.di.storage.adapter import S3StorageAdapter

pytestmark = pytest.mark.no_docker


def test_audit_link_retry_backoff_prevents_failed_callback_hot_loop() -> None:
    assert [audit_link_retry_delay_seconds(attempt) for attempt in range(7)] == [
        0,
        5,
        15,
        30,
        60,
        60,
        60,
    ]


def test_pc_booking_status_contract_is_lightweight_and_carries_direct_content_access() -> None:
    fields = set(PcBookingDocumentStatus.model_fields)
    assert fields == {
        "requirementRef",
        "documentId",
        "documentTypeKey",
        "uploadStatus",
        "processingStatus",
        "registeredAtUtc",
        "contentUrl",
        "contentUrlExpiresAtUtc",
        "mimeType",
    }
    assert "confidenceScore" not in fields
    assert "evidenceRegion" not in fields


def test_pc_booking_upload_returns_direct_content_access_without_exposing_storage_key() -> None:
    fields = set(PcBookingUploadData.model_fields)
    assert {
        "documentId",
        "uploadStatus",
        "processingStatus",
        "contentUrl",
        "contentUrlExpiresAtUtc",
        "mimeType",
    } == fields
    assert "logicalObjectKey" not in fields
    source = inspect.getsource(upload_pc_booking_document)
    assert "contentUrl=access.contentUrl" in source
    assert "pc_booking_content_url_not_generated_after_upload" in source


def test_pc_booking_direct_content_url_is_short_lived_and_authorized() -> None:
    assert PC_BOOKING_CONTENT_URL_TTL_SECONDS == 30 * 60
    assert set(PcBookingContentAccess.model_fields) == {
        "documentId",
        "contentUrl",
        "contentUrlExpiresAtUtc",
        "mimeType",
    }
    source = inspect.getsource(get_pc_booking_document_content_url)
    assert 'require_live_tenant_permission("di.document.content.read")' in source
    assert "_context_document" in source
    adapter_source = inspect.getsource(S3StorageAdapter.get_presigned_url)
    assert "generate_presigned_url" in adapter_source
    assert '"get_object"' in adapter_source


def test_pc_booking_extraction_contract_retains_audit_provenance_and_localization() -> None:
    fields = set(PcBookingExtractionField.model_fields)
    assert {
        "sourceFactRef",
        "sourceFactVersion",
        "fieldKey",
        "foundStatus",
        "rawValue",
        "normalizedValue",
        "confidenceScore",
        "pageNo",
        "evidenceRegion",
    }.issubset(fields)


def test_extraction_review_receives_current_processing_run_pointer() -> None:
    repository_source = inspect.getsource(get_document)
    review_source = inspect.getsource(get_pc_booking_extraction_review)
    assert "d.current_processing_run_id" in repository_source
    assert 'doc.get("current_processing_run_id")' in review_source
    assert "ef.processing_run_id = :processing_run_id" in review_source


def test_direct_intake_reuses_existing_audit_r2_key_builder() -> None:
    source = inspect.getsource(intake_document)
    assert "build_audit_original_key" in source
    assert "audit_storage_context" in source
    assert "audit_requirement_ref" in source


def test_context_list_does_not_collapse_repeatable_requirement_documents() -> None:
    source = inspect.getsource(list_pc_booking_documents)
    assert "DISTINCT ON" not in source
    assert "audit_requirement_ref IS NOT NULL" in source
    assert "ORDER BY d.registered_at_utc ASC" in source
    assert "contentUrl=access.contentUrl" in source

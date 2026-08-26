from __future__ import annotations

import inspect

import pytest

from verigence.di.api.v1.pc_booking_documents import (
    PcBookingDocumentStatus,
    PcBookingExtractionField,
    list_pc_booking_documents,
)
from verigence.di.application.intake import intake_document
from verigence.di.repositories.audit_links import audit_link_retry_delay_seconds

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


def test_pc_booking_status_contract_is_lightweight() -> None:
    fields = set(PcBookingDocumentStatus.model_fields)
    assert fields == {
        "requirementRef",
        "documentId",
        "documentTypeKey",
        "uploadStatus",
        "processingStatus",
        "registeredAtUtc",
    }
    assert "confidenceScore" not in fields
    assert "evidenceRegion" not in fields


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

"""tests/test_capture_v2_classifier_skips_extraction_for_unlinked_duplicates.py

Source-inspection guard, reversed on 2026-10-01: a classified page is queued
for reading whether or not Audit Core's checklist had an open slot for it
at upload time. Until then a second PAN, a KYC form or a UPI screenshot was
classified and left unread for ever (the requirement_ref gate). The only
reasons left not to read a classified page are a type that is not read and
a type with no published profile; both are reported on the listing.
"""
from __future__ import annotations

import inspect

import pytest

from verigence.di.workers import capture_v2_classifier


@pytest.mark.no_docker
def test_create_initial_job_no_longer_depends_on_the_checklist_slot() -> None:
    source = inspect.getsource(capture_v2_classifier)
    start = source.index("requirement_ref = requirement_map.get(accepted)")
    call_site = source.index("create_initial_job(", start)
    guard = source.rindex("if ", start, call_site)
    condition = source[guard:call_site]
    assert "skipped_reason is None" in condition
    decision = source[source.index("skipped_reason = extraction_skip_reason(", start):guard]
    assert "requirement_ref" not in decision
    assert "requires_processing" in decision
    assert "has_published_profile" in decision


@pytest.mark.no_docker
def test_only_an_unreadable_type_or_a_missing_profile_skips_reading() -> None:
    skip = capture_v2_classifier.extraction_skip_reason
    assert skip(requires_processing=True, has_published_profile=True) is None
    assert skip(requires_processing=False, has_published_profile=True) == "TYPE_NOT_READ"
    assert skip(requires_processing=True, has_published_profile=False) == "NO_PUBLISHED_PROFILE"


@pytest.mark.no_docker
def test_a_type_audit_core_asks_not_to_read_is_classified_and_not_read() -> None:
    """12 Nov 2026: what the journey already holds, UPI screenshots, pages read once merged."""
    skip = capture_v2_classifier.extraction_skip_reason
    assert skip(requires_processing=True, has_published_profile=True, skip_requested=True) == "NOT_READ_ON_REQUEST"
    assert skip(requires_processing=True, has_published_profile=True, skip_requested=False) is None
    # A type that is not read at all keeps its own reason.
    assert skip(requires_processing=False, has_published_profile=True, skip_requested=True) == "TYPE_NOT_READ"
    source = inspect.getsource(capture_v2_classifier)
    assert "u.read_skip_document_type_keys" in source
    assert 'skip_requested=accepted in set(row.get("read_skip_document_type_keys") or [])' in source

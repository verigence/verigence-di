"""Gemini's Flex tier for uploads nobody waits on (product owner 2026-11-12, migration 0067).

Flex is priced like the Batch API (half the standard price) and answers the same call in
minutes; DI asks for it on an upload's first classification and first reading only, so a
retry goes to the standard tier and the retry rule still holds."""
from __future__ import annotations

import inspect

import pytest

from verigence.di.document_ai import gemini_cost
from verigence.di.document_ai.gemini_cost import (
    FLEX_TIER,
    GEMINI_TIER,
    STANDARD_TIER,
    apply_service_tier,
    first_attempt_tier,
    tier_timeout,
)

pytestmark = pytest.mark.no_docker


def test_flex_is_asked_for_only_when_the_job_says_so() -> None:
    body: dict = {}
    assert apply_service_tier(body) == STANDARD_TIER and "service_tier" not in body
    assert tier_timeout(30.0, 360.0) == 30.0
    token = GEMINI_TIER.set(FLEX_TIER)
    try:
        assert apply_service_tier(body) == FLEX_TIER and body["service_tier"] == "flex"
        assert tier_timeout(30.0, 360.0) == 360.0
        assert gemini_cost.usage_from_response({}).service_tier == FLEX_TIER
    finally:
        GEMINI_TIER.reset(token)
    assert gemini_cost.usage_from_response({}).service_tier == STANDARD_TIER


def test_only_a_flex_upload_s_first_try_goes_to_flex() -> None:
    assert first_attempt_tier("FLEX", True) == FLEX_TIER
    assert first_attempt_tier("FLEX", False) == STANDARD_TIER
    assert first_attempt_tier("STANDARD", True) == STANDARD_TIER
    assert first_attempt_tier(None, True) == STANDARD_TIER


def test_the_flex_wait_stays_inside_the_job_lease() -> None:
    from verigence.di.settings import Settings

    fields = Settings.model_fields
    assert fields["docai_gemini_flex_timeout_seconds"].default < fields["worker_lease_timeout_minutes"].default * 60


def test_both_workers_set_the_tier_around_their_gemini_call() -> None:
    from verigence.di.workers import capture_v2_classifier, processor

    classifier = inspect.getsource(capture_v2_classifier)
    assert 'first_attempt_tier(row.get("gemini_tier"), attempt_no == 1)' in classifier
    worker = inspect.getsource(processor)
    assert 'first_attempt_tier(job.get("capture_v2_gemini_tier"), job_type == "INITIAL")' in worker

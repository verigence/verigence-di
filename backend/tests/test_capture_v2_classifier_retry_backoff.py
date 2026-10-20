"""Product owner's retry rule (2026-10-20): a Gemini failure is tried again
10 and 20 minutes later (three attempts), then once that night; a technical
failure gets two attempts in all, two minutes apart; a failure the page
itself decides is never retried. Classification and extraction share it."""

from __future__ import annotations

import pytest

from verigence.di.retry_policy import (
    AI_MAX_ATTEMPTS,
    CLASSIFICATION_NIGHT_ATTEMPT_NO,
    TECHNICAL_MAX_ATTEMPTS,
    failure_kind,
    retry_delay_seconds,
)
from verigence.di.runtime_errors import TechnicalFailure
from verigence.di.workers.capture_v2_classifier import (
    CLASSIFICATION_MAX_ATTEMPTS,
    _retry_delay_seconds,
)

pytestmark = pytest.mark.no_docker


@pytest.mark.parametrize(
    "code",
    [
        "DOCUMENT_AI_RATE_LIMITED",
        "DOCUMENT_AI_UNAVAILABLE",
        "DOCUMENT_AI_RESPONSE_INVALID",
        "CLASSIFICATION_PROVIDER_ERROR",
        "EXTRACTION_PROVIDER_ERROR",
    ],
)
def test_an_ai_failure_is_retried_at_10_then_20_minutes_and_then_stops(code: str) -> None:
    assert failure_kind(code) == "AI"
    assert retry_delay_seconds(code, retryable=True, attempt_no=1) == 600
    assert retry_delay_seconds(code, retryable=True, attempt_no=2) == 1200
    assert retry_delay_seconds(code, retryable=True, attempt_no=3) is None
    assert AI_MAX_ATTEMPTS == 3
    # the night attempt is one past the daytime ladder, so its failure is final
    assert CLASSIFICATION_NIGHT_ATTEMPT_NO == 4
    assert retry_delay_seconds(code, retryable=True, attempt_no=CLASSIFICATION_NIGHT_ATTEMPT_NO) is None


@pytest.mark.parametrize(
    "code",
    ["STORAGE_READ_ERROR", "DATABASE_UNAVAILABLE", "WORKER_INTERNAL_ERROR", "CLASSIFICATION_RETRY"],
)
def test_a_technical_failure_gets_two_attempts_two_minutes_apart(code: str) -> None:
    assert failure_kind(code) == "TECHNICAL"
    assert retry_delay_seconds(code, retryable=True, attempt_no=1) == 120
    assert retry_delay_seconds(code, retryable=True, attempt_no=2) is None
    assert TECHNICAL_MAX_ATTEMPTS == 2
    # an expired lease (scheduler/beat.py) is technical: same two attempts
    assert CLASSIFICATION_MAX_ATTEMPTS == 2


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("DOCUMENT_AI_CONTENT_BLOCKED", "DOCUMENT"),
        ("INVALID_FILE_CONTENT", "DOCUMENT"),
        ("DI_QUALITY_IMAGE_BLUR_SCORE", "DOCUMENT"),
        ("DOCUMENT_AI_REQUEST_REJECTED", "AI"),
        ("DOCUMENT_TYPE_NOT_FOUND", "CONFIGURATION"),
        ("DOCUMENT_AI_NOT_CONFIGURED", "CONFIGURATION"),
    ],
)
def test_a_refusal_is_never_retried(code: str, kind: str) -> None:
    assert failure_kind(code) == kind
    assert retry_delay_seconds(code, retryable=False, attempt_no=1) is None
    # even if a caller marked it retryable, a page-decided outcome is final
    if kind in ("DOCUMENT", "CONFIGURATION"):
        assert retry_delay_seconds(code, retryable=True, attempt_no=1) is None


def test_the_classifier_follows_the_shared_ladder() -> None:
    ai = TechnicalFailure("DOCUMENT_AI_UNAVAILABLE", "x", True)
    technical = TechnicalFailure("STORAGE_READ_ERROR", "x", True)
    refused = TechnicalFailure("INVALID_FILE_CONTENT", "x", False)
    assert [_retry_delay_seconds(ai, n) for n in (1, 2, 3)] == [600, 1200, None]
    assert [_retry_delay_seconds(technical, n) for n in (1, 2)] == [120, None]
    assert _retry_delay_seconds(refused, 1) is None


@pytest.mark.parametrize("status", [401, 403, 404])
def test_gemini_refusing_our_key_or_model_is_configuration_not_the_page(status: int) -> None:
    """2026-10-20 review (S8): an expired key or a wrong model name must not
    tell the PC to re-upload a good page."""
    from verigence.di.document_ai.gemini_adapter import GeminiApiError
    from verigence.di.document_ai.v2_classifier import _http_failure
    from verigence.di.runtime_errors import technical_failure

    assert GeminiApiError(status, "x").technical_code == "DOCUMENT_AI_NOT_CONFIGURED"
    assert (_http_failure(status).technical_code, _http_failure(status).retryable) == (
        "DOCUMENT_AI_NOT_CONFIGURED", False)
    failure = technical_failure(GeminiApiError(status, "x"), operation="extraction_provider")
    assert (failure.code, failure.retryable, failure.category) == ("DOCUMENT_AI_NOT_CONFIGURED", False, "CONFIGURATION")
    assert retry_delay_seconds("DOCUMENT_AI_NOT_CONFIGURED", retryable=False, attempt_no=1) is None

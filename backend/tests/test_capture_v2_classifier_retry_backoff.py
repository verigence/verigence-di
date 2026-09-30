"""A Gemini quota hit or outage during classification gets one more attempt
five minutes later, then the page is left for the nightly sweep: two
attempts in all, never a burst against the model."""

from __future__ import annotations

import pytest

from verigence.di.workers.capture_v2_classifier import (
    _RETRYABLE_RETRY_DELAYS_SECONDS,
    CLASSIFICATION_MAX_ATTEMPTS,
    _retry_delay_seconds,
)


@pytest.mark.no_docker
def test_a_retryable_failure_is_tried_once_more_after_five_minutes() -> None:
    assert CLASSIFICATION_MAX_ATTEMPTS == 2
    assert _RETRYABLE_RETRY_DELAYS_SECONDS == (300,)
    assert _retry_delay_seconds(1) == 300

"""A Gemini quota hit or outage during classification is a wait, not a
failure: attempts are spaced over half an hour before the page is given up
on. Nothing here spends more on the model: a retry only follows a call
that was rejected or never completed."""

from __future__ import annotations

import pytest

from verigence.di.workers.capture_v2_classifier import (
    _RETRYABLE_RETRY_DELAYS_SECONDS,
    CLASSIFICATION_MAX_ATTEMPTS,
    _retry_delay_seconds,
)


@pytest.mark.no_docker
def test_retryable_failures_back_off_over_half_an_hour_then_stop() -> None:
    assert CLASSIFICATION_MAX_ATTEMPTS == 5
    assert [_retry_delay_seconds(n) for n in range(1, CLASSIFICATION_MAX_ATTEMPTS)] == [
        60,
        180,
        600,
        1200,
    ]
    # ~34 minutes in all, inside Audit Core's one-hour page deadline.
    assert sum(_RETRYABLE_RETRY_DELAYS_SECONDS) == 2040

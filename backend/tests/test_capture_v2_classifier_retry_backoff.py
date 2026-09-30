"""A Gemini quota hit or outage during classification is a wait, not a
failure: attempts are spaced over half an hour before the page is given up
on. A non-retryable failure keeps its single quick retry. Nothing here
spends more on the model: a retry only follows a call that was rejected or
never completed."""

from __future__ import annotations

import pytest

from verigence.di.workers.capture_v2_classifier import (
    _RETRYABLE_RETRY_DELAYS_SECONDS,
    _retry_delay_seconds,
)


@pytest.mark.no_docker
def test_retryable_failures_back_off_over_half_an_hour_then_stop() -> None:
    delays = [_retry_delay_seconds(n, retryable=True) for n in range(1, 6)]
    assert delays == [60, 180, 600, 1200, None]
    # ~34 minutes in all, inside Audit Core's one-hour page deadline.
    assert sum(_RETRYABLE_RETRY_DELAYS_SECONDS) == 2040


@pytest.mark.no_docker
def test_non_retryable_failures_keep_one_quick_retry() -> None:
    assert _retry_delay_seconds(1, retryable=False) == 1
    assert _retry_delay_seconds(2, retryable=False) is None

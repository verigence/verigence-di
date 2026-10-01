"""A worker that is alive but reads nothing while work is due is reported
(decision 2026-10-01): six heartbeats in a row with pending jobs and an
unchanged processed counter."""
from __future__ import annotations

import pytest

from verigence.di.workers.heartbeat import STALL_HEARTBEATS, stall_detected

pytestmark = pytest.mark.no_docker


def test_idle_with_nothing_due_is_not_a_stall() -> None:
    assert stall_detected(pending=0, processed_before=5, processed_now=5, idle_beats=10) == (False, 0)


def test_progress_resets_the_idle_count() -> None:
    assert stall_detected(pending=3, processed_before=5, processed_now=6, idle_beats=4) == (False, 0)


def test_work_due_and_no_progress_stalls_after_the_threshold() -> None:
    idle = 0
    for beat in range(1, STALL_HEARTBEATS + 1):
        stalled, idle = stall_detected(pending=3, processed_before=5, processed_now=5, idle_beats=idle)
        assert idle == beat
        assert stalled is (beat >= STALL_HEARTBEATS)

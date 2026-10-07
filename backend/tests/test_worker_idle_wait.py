"""A worker lane that finds no work waits on a timer or a job notification. Each
timed-out wait must be gone afterwards: left behind, they piled up (one per lane
per half second) and grew worker memory in a straight line until the next redeploy."""

from __future__ import annotations

import asyncio

import pytest

from verigence.di.workers.idle_wait import idle_wait


@pytest.mark.no_docker
async def test_timed_out_waits_leave_nothing_waiting() -> None:
    event = asyncio.Event()
    for _ in range(200):
        event.clear()
        await idle_wait(event, 0.0005)
    assert len(event._waiters) == 0  # noqa: SLF001 - the point of the test


@pytest.mark.no_docker
async def test_a_notification_ends_the_wait_at_once() -> None:
    event = asyncio.Event()
    waiter = asyncio.create_task(idle_wait(event, 30))
    await asyncio.sleep(0)
    event.set()
    await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.no_docker
def test_the_backstop_is_six_seconds_while_notifications_work() -> None:
    from verigence.di.workers.idle_wait import NOTIFY_BACKSTOP_SECONDS

    assert NOTIFY_BACKSTOP_SECONDS == 6.0

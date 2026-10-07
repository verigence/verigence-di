"""idle_wait.py -- how a worker lane sleeps between looks at the job table."""

from __future__ import annotations

import asyncio
import contextlib

# While the job-notification listener is up, a notification wakes a lane the moment a job is
# queued; this timer is only the safety net for a job queued without one (a nightly sweep, a
# retry whose time has come). Without a listener the lanes keep polling quickly.
NOTIFY_BACKSTOP_SECONDS = 6.0


async def idle_wait(event: asyncio.Event, timeout: float) -> None:
    """Wait until ``event`` is set or ``timeout`` seconds pass, whichever is first.

    The wait is cancelled when the time runs out. It used to be wrapped in
    ``asyncio.shield``, which kept every timed-out wait alive: a lane that found
    no work every half second left one more waiting task behind each time, and
    none of them were released until a job notification arrived. Worker memory
    on DEV grew in a straight line (about 0.5 GB per six hours) until the next
    redeploy.
    """
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=timeout)

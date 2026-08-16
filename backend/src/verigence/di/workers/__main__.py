"""Standalone DI background runtime for Railway.

Runs the ProcessingWorker and EODRetryScheduler together in the dedicated
worker service. The HTTP API should run with DI_WORKER_ENABLED=false so the
background responsibilities have exactly one owner.
"""
from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from verigence.di.scheduler.beat import get_eod_scheduler
from verigence.di.workers.processor import get_worker


async def main() -> None:
    """Run the processing worker and EOD scheduler until termination."""
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):  # pragma: no cover - Windows fallback
            loop.add_signal_handler(sig, stopped.set)

    worker = get_worker()
    scheduler = get_eod_scheduler()

    worker.start()
    scheduler_started = False
    try:
        scheduler.start()
        scheduler_started = True
        print("DI_WORKER_STARTED=PASS", flush=True)
        print("DI_EOD_SCHEDULER_STARTED=PASS", flush=True)
        await stopped.wait()
    finally:
        await worker.stop()
        if scheduler_started:
            scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())

"""workers/__main__.py — Standalone entry point for the processing worker.

Run as:  python -m verigence.di.workers
Used by: Docker container with START_MODE=worker
"""
from __future__ import annotations

import asyncio
import signal

import structlog

logger = structlog.get_logger(__name__)


async def _main() -> None:
    from verigence.di.scheduler.beat import EODRetryScheduler
    from verigence.di.workers.processor import ProcessingWorker

    worker = ProcessingWorker()
    scheduler = EODRetryScheduler()

    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("worker_shutdown_signal", signal=sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    logger.info("di_worker_starting")
    worker.start()
    scheduler.start()

    await stop_event.wait()

    logger.info("di_worker_stopping")
    await worker.stop()
    scheduler.stop()
    logger.info("di_worker_stopped")


if __name__ == "__main__":
    asyncio.run(_main())

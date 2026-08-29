"""workers/__main__.py — Standalone entry point for DI background workers.

Run as:  python -m verigence.di.workers
Used by: dedicated Railway worker service
"""
from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import structlog

logger = structlog.get_logger(__name__)
_CAPTURE_V2_CONCURRENCY = 6


async def _main() -> None:
    from verigence.di.logging_config import configure_logging  # noqa: PLC0415
    configure_logging()

    from verigence.di.document_ai.v2_classifier import close_v2_classifier_client
    from verigence.di.scheduler.beat import EODRetryScheduler
    from verigence.di.workers.capture_v2_classifier import CaptureV2ClassificationWorker
    from verigence.di.workers.processor import ProcessingWorker

    worker = ProcessingWorker()
    capture_v2_workers = [
        CaptureV2ClassificationWorker() for _ in range(_CAPTURE_V2_CONCURRENCY)
    ]
    scheduler = EODRetryScheduler()

    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("worker_shutdown_signal", signal=sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # pragma: no cover - non-POSIX fallback
            loop.add_signal_handler(sig, _handle_signal, sig)

    logger.info("di_worker_starting")
    worker.start()
    for capture_v2_worker in capture_v2_workers:
        capture_v2_worker.start()
    logger.info(
        "capture_v2_classifier_pool_started",
        concurrency=_CAPTURE_V2_CONCURRENCY,
    )
    scheduler_started = False
    try:
        scheduler.start()
        scheduler_started = True
        # Stable deployment verification markers consumed by deploy-dev.yml.
        print("DI_WORKER_STARTED=PASS", flush=True)
        print("DI_CAPTURE_V2_CLASSIFIER_STARTED=PASS", flush=True)
        print(f"DI_CAPTURE_V2_CLASSIFIER_CONCURRENCY={_CAPTURE_V2_CONCURRENCY}", flush=True)
        print("DI_EOD_SCHEDULER_STARTED=PASS", flush=True)

        await stop_event.wait()
    finally:
        logger.info("di_worker_stopping")
        await asyncio.gather(
            *(capture_v2_worker.stop() for capture_v2_worker in capture_v2_workers)
        )
        await worker.stop()
        await close_v2_classifier_client()
        if scheduler_started:
            scheduler.stop()
        logger.info("di_worker_stopped")


if __name__ == "__main__":
    asyncio.run(_main())

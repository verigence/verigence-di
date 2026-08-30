"""workers/__main__.py — Standalone entry point for DI background workers.

Run as:  python -m verigence.di.workers
Used by: dedicated Railway worker services.

Runtime topology is selected with DI_WORKER_MODE:
- combined: historical/local topology (legacy + V2 + scheduler)
- legacy: one unchanged V1/legacy processing lane + EOD scheduler
- v2: bounded V2 classification + extraction pools only
"""
from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress

import structlog

logger = structlog.get_logger(__name__)


async def _main() -> None:
    from verigence.di.logging_config import configure_logging  # noqa: PLC0415

    configure_logging()

    from verigence.di.document_ai.v2_classifier import close_v2_classifier_client
    from verigence.di.scheduler.beat import EODRetryScheduler
    from verigence.di.settings import WorkerMode, get_settings
    from verigence.di.workers.capture_v2_classifier import CaptureV2ClassificationWorker
    from verigence.di.workers.processor import ProcessingWorker, V2ProcessingWorker

    settings = get_settings()
    mode = settings.worker_mode
    include_legacy = mode in {WorkerMode.COMBINED, WorkerMode.LEGACY}
    include_v2 = mode in {WorkerMode.COMBINED, WorkerMode.V2}

    legacy_worker = ProcessingWorker() if include_legacy else None
    capture_v2_workers = (
        [
            CaptureV2ClassificationWorker()
            for _ in range(settings.v2_classification_concurrency)
        ]
        if include_v2
        else []
    )
    v2_processing_workers = (
        [
            V2ProcessingWorker(slot + 1)
            for slot in range(settings.v2_extraction_concurrency)
        ]
        if include_v2
        else []
    )
    scheduler = EODRetryScheduler() if include_legacy else None

    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("worker_shutdown_signal", signal=sig.name, worker_mode=mode.value)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # pragma: no cover - non-POSIX fallback
            loop.add_signal_handler(sig, _handle_signal, sig)

    replica_region = os.getenv("RAILWAY_REPLICA_REGION", "unknown")
    replica_id = os.getenv("RAILWAY_REPLICA_ID", "unknown")
    logger.info(
        "di_worker_starting",
        worker_mode=mode.value,
        replica_region=replica_region,
        replica_id=replica_id,
        v2_classification_concurrency=(
            settings.v2_classification_concurrency if include_v2 else 0
        ),
        v2_extraction_concurrency=(settings.v2_extraction_concurrency if include_v2 else 0),
    )

    if legacy_worker is not None:
        legacy_worker.start()
    for capture_worker in capture_v2_workers:
        capture_worker.start()
    for processing_worker in v2_processing_workers:
        processing_worker.start()

    scheduler_started = False
    try:
        if scheduler is not None:
            scheduler.start()
            scheduler_started = True

        # Stable deployment verification markers consumed by deploy-dev.yml.
        print(f"DI_WORKER_MODE={mode.value}", flush=True)
        print(f"DI_WORKER_REPLICA_REGION={replica_region}", flush=True)
        print(f"DI_WORKER_REPLICA_ID={replica_id}", flush=True)
        if include_legacy:
            print("DI_WORKER_STARTED=PASS", flush=True)
            print("DI_LEGACY_PROCESSING_STARTED=PASS", flush=True)
            print("DI_EOD_SCHEDULER_STARTED=PASS", flush=True)
        if include_v2:
            print("DI_V2_WORKER_STARTED=PASS", flush=True)
            print("DI_CAPTURE_V2_CLASSIFIER_STARTED=PASS", flush=True)
            print(
                "DI_CAPTURE_V2_CLASSIFIER_CONCURRENCY="
                f"{settings.v2_classification_concurrency}",
                flush=True,
            )
            print("DI_V2_PROCESSING_POOL_STARTED=PASS", flush=True)
            print(
                f"DI_V2_EXTRACTION_CONCURRENCY={settings.v2_extraction_concurrency}",
                flush=True,
            )

        await stop_event.wait()
    finally:
        logger.info("di_worker_stopping", worker_mode=mode.value)
        await asyncio.gather(
            *(capture_worker.stop() for capture_worker in capture_v2_workers),
            *(processing_worker.stop() for processing_worker in v2_processing_workers),
        )
        if legacy_worker is not None:
            await legacy_worker.stop()
        if include_v2:
            await close_v2_classifier_client()
        if scheduler_started and scheduler is not None:
            scheduler.stop()
        logger.info("di_worker_stopped", worker_mode=mode.value)


if __name__ == "__main__":
    asyncio.run(_main())

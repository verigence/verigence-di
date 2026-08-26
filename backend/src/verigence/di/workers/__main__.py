"""workers/__main__.py — Standalone entry point for the processing worker.

Run as:  python -m verigence.di.workers
Used by: dedicated Railway worker service
"""
from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import structlog

logger = structlog.get_logger(__name__)


async def _emit_dev_aadhaar_runtime_diagnostic() -> None:
    """Emit non-PII Aadhaar run/fact metadata once at DEV worker startup."""
    from sqlalchemy import text  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    from verigence.di.settings import Environment, get_settings  # noqa: PLC0415

    settings = get_settings()
    if settings.env != Environment.DEV:
        return

    engine = create_async_engine(str(settings.database_url), echo=False)
    try:
        async with engine.connect() as connection:
            version = (
                await connection.execute(text("SELECT version_num FROM docintel.alembic_version"))
            ).scalar_one_or_none()
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT d.tenant_id,
                               d.document_id,
                               d.document_type_hint_key,
                               dt.document_type_key,
                               d.upload_status,
                               d.processing_status,
                               d.current_processing_run_id,
                               d.registered_at_utc
                        FROM docintel.documents d
                        LEFT JOIN docintel.document_types dt
                          ON dt.document_type_id = d.document_type_id
                        WHERE lower(COALESCE(d.document_type_hint_key, '')) = 'aadhaar'
                           OR lower(COALESCE(dt.document_type_key, '')) = 'aadhaar'
                        ORDER BY d.registered_at_utc DESC
                        LIMIT 10
                        """
                    )
                )
            ).mappings().all()
            logger.info(
                "dev_aadhaar_runtime_summary",
                alembic_version=str(version) if version is not None else None,
                document_count=len(rows),
            )
            for row in rows:
                tenant_id = str(row["tenant_id"])
                document_id = row["document_id"]
                current_run_id = row["current_processing_run_id"]

                total_fact_count = (
                    await connection.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM docintel.extracted_facts
                            WHERE tenant_id = :tenant_id
                              AND document_id = :document_id
                            """
                        ),
                        {"tenant_id": tenant_id, "document_id": document_id},
                    )
                ).scalar_one()

                current_run_fact_count = 0
                current_run_status = None
                current_run_field_keys: list[str] = []
                if current_run_id is not None:
                    current_run_fact_count = (
                        await connection.execute(
                            text(
                                """
                                SELECT count(*)
                                FROM docintel.extracted_facts
                                WHERE tenant_id = :tenant_id
                                  AND document_id = :document_id
                                  AND processing_run_id = :processing_run_id
                                """
                            ),
                            {
                                "tenant_id": tenant_id,
                                "document_id": document_id,
                                "processing_run_id": current_run_id,
                            },
                        )
                    ).scalar_one()
                    current_run_status = (
                        await connection.execute(
                            text(
                                """
                                SELECT run_status
                                FROM docintel.processing_runs
                                WHERE tenant_id = :tenant_id
                                  AND processing_run_id = :processing_run_id
                                """
                            ),
                            {
                                "tenant_id": tenant_id,
                                "processing_run_id": current_run_id,
                            },
                        )
                    ).scalar_one_or_none()
                    current_run_field_keys = list(
                        (
                            await connection.execute(
                                text(
                                    """
                                    SELECT cf.field_key
                                    FROM docintel.extracted_facts ef
                                    JOIN docintel.canonical_fields cf
                                      ON cf.canonical_field_id = ef.canonical_field_id
                                    WHERE ef.tenant_id = :tenant_id
                                      AND ef.document_id = :document_id
                                      AND ef.processing_run_id = :processing_run_id
                                    ORDER BY cf.field_key
                                    """
                                ),
                                {
                                    "tenant_id": tenant_id,
                                    "document_id": document_id,
                                    "processing_run_id": current_run_id,
                                },
                            )
                        ).scalars().all()
                    )

                logger.info(
                    "dev_aadhaar_runtime_document",
                    tenant_id=tenant_id,
                    document_id=str(document_id),
                    document_type_hint_key=row["document_type_hint_key"],
                    classified_document_type_key=row["document_type_key"],
                    upload_status=str(row["upload_status"]),
                    processing_status=str(row["processing_status"]),
                    current_processing_run_id=(
                        str(current_run_id) if current_run_id is not None else None
                    ),
                    current_run_status=(
                        str(current_run_status) if current_run_status is not None else None
                    ),
                    total_fact_count=int(total_fact_count),
                    current_run_fact_count=int(current_run_fact_count),
                    current_run_field_keys=current_run_field_keys,
                    registered_at_utc=str(row["registered_at_utc"]),
                )
    except Exception as exc:
        logger.warning(
            "dev_aadhaar_runtime_diagnostic_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
    finally:
        await engine.dispose()


async def _main() -> None:
    from verigence.di.logging_config import configure_logging  # noqa: PLC0415
    configure_logging()

    from verigence.di.scheduler.beat import EODRetryScheduler
    from verigence.di.workers.processor import ProcessingWorker

    await _emit_dev_aadhaar_runtime_diagnostic()

    worker = ProcessingWorker()
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
    scheduler_started = False
    try:
        scheduler.start()
        scheduler_started = True
        # Stable deployment verification markers consumed by deploy-dev.yml.
        print("DI_WORKER_STARTED=PASS", flush=True)
        print("DI_EOD_SCHEDULER_STARTED=PASS", flush=True)

        await stop_event.wait()
    finally:
        logger.info("di_worker_stopping")
        await worker.stop()
        if scheduler_started:
            scheduler.stop()
        logger.info("di_worker_stopped")


if __name__ == "__main__":
    asyncio.run(_main())

"""workers/processor.py — Async polling loop for the Processing Worker.

Implements the outer loop of DI_LLD_v2.2 §Processing Worker:
  - Poll for PENDING jobs using SELECT ... FOR UPDATE SKIP LOCKED
  - Call job_runner.run_processing_job() for each claimed job
  - On success: commit + complete_job(COMPLETED)
  - On any failure (retryable or non-retryable): D24 backout path —
      set Document FAILED/NOT_CONFIRMED, mark job FAILED,
      insert backout_jobs row with TTL=DI_BACKOUT_TTL_HOURS (default 12 h)
  - Sleep poll_interval when no jobs are available

Lifecycle:
  - start()  — begins the background task (called from FastAPI lifespan)
  - stop()   — signals graceful shutdown (called from FastAPI lifespan)

Configuration:
  - DI_WORKER_POLL_INTERVAL_SECONDS  (default: 5)
  - DI_WORKER_ID                     (default: hostname + PID)
  - DI_BACKOUT_TTL_HOURS             (default: 12)
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.document_ai.adapter import get_document_ai_adapter
from verigence.di.repositories.backout import insert_backout_job
from verigence.di.repositories.processing_jobs import (
    claim_next_job,
    complete_job,
    fail_job,
)
from verigence.di.settings import get_settings
from verigence.di.workers.job_runner import run_processing_job

logger = structlog.get_logger(__name__)


def _default_worker_id() -> str:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    return f"{hostname}.{os.getpid()}"


class ProcessingWorker:
    """Background processing worker — runs as a long-lived asyncio task."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        """Start the background poll loop. Called from FastAPI lifespan."""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="processing-worker")
        logger.info("processing_worker_started")

    async def stop(self) -> None:
        """Signal stop and wait for graceful shutdown."""
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        logger.info("processing_worker_stopped")

    async def _run(self) -> None:
        settings = get_settings()
        poll_interval: int = getattr(settings, "worker_poll_interval_seconds", 5)
        worker_id = getattr(settings, "worker_id", None) or _default_worker_id()

        engine = create_async_engine(str(settings.database_url), echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        ai_adapter = get_document_ai_adapter()

        log = logger.bind(worker_id=worker_id)
        log.info("processing_worker_loop_started", poll_interval=poll_interval)

        try:
            while not self._stop_event.is_set():
                try:
                    did_work = await self._process_one(
                        session_factory=session_factory,
                        worker_id=worker_id,
                        ai_adapter=ai_adapter,
                        log=log,
                    )
                except Exception as exc:
                    log.exception("processing_worker_loop_error", error=str(exc))
                    did_work = False

                if not did_work:
                    # No jobs available — sleep before next poll
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=poll_interval,
                        )
        finally:
            await engine.dispose()

    async def _process_one(
        self,
        *,
        session_factory: async_sessionmaker,
        worker_id: str,
        ai_adapter,
        log,
    ) -> bool:
        """Claim and process one job. Returns True if a job was processed."""
        async with session_factory() as session:
            # Claim inside a transaction so SKIP LOCKED works correctly
            async with session.begin():
                job = await claim_next_job(session, worker_id=worker_id)

            if job is None:
                return False

        tenant_id: str = job["tenant_id"]
        job_id: uuid.UUID = job["processing_job_id"]
        document_id: uuid.UUID = job["document_id"]
        correlation_id: str = job["correlation_id"]
        job_type: str = job["job_type"]

        job_log = log.bind(
            tenant_id=tenant_id,
            document_id=str(document_id),
            processing_job_id=str(job_id),
            correlation_id=correlation_id,
            job_type=job_type,
        )
        job_log.info("job_claimed")

        # Run the job in its own session/transaction
        async with session_factory() as session:
            try:
                async with session.begin():
                    result = await run_processing_job(
                        session=session,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        processing_job_id=job_id,
                        job_type=job_type,
                        correlation_id=correlation_id,
                        ai_adapter=ai_adapter,
                    )

                if result.success:
                    # Commit already happened via session.begin() context manager
                    # Complete the job
                    async with session_factory() as s2, s2.begin():
                        await complete_job(
                            s2,
                            tenant_id=tenant_id,
                            processing_job_id=job_id,
                            success=True,
                        )
                    job_log.info("job_completed",
                                 confidence_score=str(result.confidence_score),
                                 human_verification_status=result.human_verification_status)
                else:
                    # The run_processing_job already handled its own rollback via
                    # the ProcessingError handler inside it; we need to clean up
                    # the job and document
                    await _handle_failure(
                        session_factory=session_factory,
                        tenant_id=tenant_id,
                        job_id=job_id,
                        document_id=document_id,
                        processing_run_id=result.processing_run_id,
                        error_code=result.error_code,
                        error_detail=result.error_detail,
                        retryable=result.retryable,
                        job_log=job_log,
                    )

            except Exception as exc:
                # Catch anything that escaped run_processing_job (should not happen)
                # processing_run_id is unknown here — the run may not have been created
                job_log.exception("job_runner_unexpected_escape", error=str(exc))
                await _handle_failure(
                    session_factory=session_factory,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    document_id=document_id,
                    processing_run_id=None,
                    error_code="WORKER_INTERNAL_ERROR",
                    error_detail=str(exc),
                    retryable=True,
                    job_log=job_log,
                )

        return True


async def _handle_failure(
    *,
    session_factory: async_sessionmaker,
    tenant_id: str,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    processing_run_id: uuid.UUID | None,
    error_code: str | None,
    error_detail: str | None,
    retryable: bool,
    job_log,
) -> None:
    """D24 backout path — write FAILED state + insert backout_jobs row.

    All failures (retryable or non-retryable) follow the same path:
      1. Mark the processing job FAILED + set document FAILED/NOT_CONFIRMED
      2. Insert a backout_jobs row with a TTL (default 12 h)

    The RETRY_PENDING document state is no longer used here. The EOD Retry
    Scheduler path remains intact for any document explicitly left in that
    state through other mechanisms, but under normal operation all failures
    go to backout immediately.
    """
    from datetime import UTC, datetime

    from sqlalchemy import text

    settings = get_settings()
    ttl_hours: int = settings.backout_ttl_hours
    error_class = "RETRYABLE" if retryable else "NON_RETRYABLE"

    async with session_factory() as session, session.begin():
        # 1a. Mark job FAILED
        await fail_job(
            session,
            tenant_id=tenant_id,
            processing_job_id=job_id,
            document_id=document_id,
            error_code=error_code,
            error_detail=error_detail,
        )

        # 1b. Ensure document is FAILED/NOT_CONFIRMED (fail_job already does this,
        #     but be explicit in case the document was left in PROCESSING state
        #     by a crash before fail_job was called)
        await session.execute(
            text("""
                UPDATE docintel.documents
                SET processing_status     = 'FAILED',
                    confirmation_status   = 'NOT_CONFIRMED',
                    processing_failure_code   = :error_code,
                    processing_failure_detail = :error_detail,
                    updated_at_utc        = :now
                WHERE tenant_id = :tid AND document_id = :doc_id
                  AND processing_status != 'PROCESSED'
            """),
            {
                "tid": tenant_id,
                "doc_id": document_id,
                "error_code": error_code,
                "error_detail": error_detail,
                "now": datetime.now(UTC),
            },
        )

        # 2. Insert backout row (upsert — safe on second attempt for same document)
        await insert_backout_job(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            processing_job_id=job_id,
            processing_run_id=processing_run_id,
            error_class=error_class,
            error_code=error_code,
            error_detail=error_detail,
            ttl_hours=ttl_hours,
        )

    job_log.warning(
        "job_failed_backout",
        error_class=error_class,
        error_code=error_code,
        error_detail=error_detail,
        ttl_hours=ttl_hours,
    )


# ── Module-level singleton ────────────────────────────────────────────────────
# The FastAPI lifespan imports this to start/stop the worker.

_worker = ProcessingWorker()


def get_worker() -> ProcessingWorker:
    """Return the module-level ProcessingWorker singleton."""
    return _worker

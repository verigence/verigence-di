"""workers/processor.py — Async polling loop for the Processing Worker.

Implements the outer loop of DI_LLD_v2.2 §Processing Worker:
  - Poll for PENDING jobs using SELECT ... FOR UPDATE SKIP LOCKED
  - Call job_runner.run_processing_job() for each claimed job
  - On success: commit + complete_job(COMPLETED)
  - On any failure (retryable or non-retryable): D24 backout path —
      set Document FAILED/NOT_CONFIRMED, mark job FAILED,
      insert backout_jobs row with TTL=DI_BACKOUT_TTL_HOURS (default 12 h)
  - When idle: wake immediately via pg_notify (DI_WORKER_NOTIFY_DB_URL set)
    or sleep poll_interval as fallback

Lifecycle:
  - start()  — begins the background task (called from FastAPI lifespan)
  - stop()   — signals graceful shutdown (called from FastAPI lifespan)
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from typing import Any

import structlog
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.document_ai.adapter import DocumentAIAdapter, get_document_ai_adapter
from verigence.di.otel import processing_job_span, record_processing_job
from verigence.di.repositories.backout import insert_backout_job
from verigence.di.repositories.processing_jobs import (
    claim_next_job,
    complete_job,
    fail_job,
    retry_job,
)
from verigence.di.settings import get_settings
from verigence.di.workers.job_runner import run_processing_job

logger = structlog.get_logger(__name__)

_NOTIFY_CHANNEL = "di_processing_jobs"


def _default_worker_id() -> str:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    return f"{hostname}.{os.getpid()}"


def _asyncpg_url(url: str) -> str:
    """Strip SQLAlchemy driver prefix so asyncpg.connect() accepts the URL."""
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )


class ProcessingWorker:
    """Background processing worker — runs as a long-lived asyncio task."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._notify_event = asyncio.Event()
        self._notify_conn: Any | None = None

    def start(self) -> None:
        """Start the background poll loop. Called from FastAPI lifespan."""
        self._stop_event.clear()
        self._notify_event.clear()
        self._task = asyncio.create_task(self._run(), name="processing-worker")
        logger.info("processing_worker_started")

    async def stop(self) -> None:
        """Signal stop and wait for graceful shutdown."""
        self._stop_event.set()
        self._notify_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        if self._notify_conn is not None:
            with contextlib.suppress(Exception):
                await self._notify_conn.close()
            self._notify_conn = None
        logger.info("processing_worker_stopped")

    async def _open_notify_conn(self, notify_db_url: str) -> bool:
        """Open a dedicated raw asyncpg connection for LISTEN."""
        try:
            import asyncpg
        except ImportError:
            logger.warning("notify_listener_unavailable", reason="asyncpg_not_installed")
            return False

        def _on_notify(
            connection: object,
            pid: int,
            channel: str,
            payload: str,
        ) -> None:
            del connection, pid
            logger.info(
                "notify_received",
                channel=channel,
                processing_job_id=payload,
            )
            self._notify_event.set()

        try:
            conn = await asyncpg.connect(_asyncpg_url(notify_db_url))
            await conn.add_listener(_NOTIFY_CHANNEL, _on_notify)
            self._notify_conn = conn
            logger.info("notify_listener_started", channel=_NOTIFY_CHANNEL)
            return True
        except Exception as exc:
            logger.warning(
                "notify_listener_failed",
                reason=str(exc),
                fallback="poll_only",
            )
            return False

    async def _run(self) -> None:
        settings = get_settings()
        poll_interval: int = getattr(settings, "worker_poll_interval_seconds", 30)
        worker_id = getattr(settings, "worker_id", None) or _default_worker_id()
        notify_db_url: str = getattr(settings, "worker_notify_db_url", "") or ""

        engine = create_async_engine(str(settings.database_url), echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        ai_adapter = get_document_ai_adapter()

        log = logger.bind(worker_id=worker_id)

        notify_active = False
        if notify_db_url.strip():
            notify_active = await self._open_notify_conn(notify_db_url)
        else:
            log.info(
                "notify_listener_fallback",
                reason="DI_WORKER_NOTIFY_DB_URL_not_set",
                poll_interval_seconds=poll_interval,
            )

        log.info(
            "processing_worker_loop_started",
            poll_interval=poll_interval,
            notify_active=notify_active,
        )

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
                    self._notify_event.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            asyncio.shield(self._notify_event.wait()),
                            timeout=poll_interval,
                        )
        finally:
            await engine.dispose()

    async def _process_one(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        ai_adapter: DocumentAIAdapter,
        log: Any,
    ) -> bool:
        """Claim and process one job. Returns True if a job was processed."""
        async with session_factory() as session:
            async with session.begin():
                job = await claim_next_job(session, worker_id=worker_id)

            if job is None:
                return False

        tenant_id: str = job["tenant_id"]
        job_id: uuid.UUID = job["processing_job_id"]
        document_id: uuid.UUID = job["document_id"]
        correlation_id: str = job["correlation_id"]
        job_type: str = job["job_type"]
        attempt_no: int = job["attempt_no"]

        job_log = log.bind(
            tenant_id=tenant_id,
            document_id=str(document_id),
            processing_job_id=str(job_id),
            correlation_id=correlation_id,
            job_type=job_type,
            attempt_no=attempt_no,
        )
        job_log.info("job_claimed")

        job_start = time.monotonic()
        with processing_job_span(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            document_id=str(document_id),
            processing_job_id=str(job_id),
            job_type=job_type,
        ) as span:
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
                        async with session_factory() as s2, s2.begin():
                            await complete_job(
                                s2,
                                tenant_id=tenant_id,
                                processing_job_id=job_id,
                                success=True,
                            )
                        total_ms = round((time.monotonic() - job_start) * 1000, 1)
                        span.set_attribute("verigence.outcome", "completed")
                        record_processing_job(
                            outcome="completed",
                            job_type=job_type,
                            duration_ms=total_ms,
                        )
                        job_log.info(
                            "job_completed",
                            confidence_score=str(result.confidence_score),
                            human_verification_status=result.human_verification_status,
                            total_duration_ms=total_ms,
                        )
                    else:
                        await _handle_failure(
                            session_factory=session_factory,
                            tenant_id=tenant_id,
                            job_id=job_id,
                            document_id=document_id,
                            processing_run_id=result.processing_run_id,
                            error_code=result.error_code,
                            error_detail=result.error_detail,
                            retryable=result.retryable,
                            attempt_no=attempt_no,
                            job_log=job_log,
                        )
                        total_ms = round((time.monotonic() - job_start) * 1000, 1)
                        outcome = (
                            "retry_pending" if result.retryable and attempt_no == 1 else "failed"
                        )
                        span.set_attribute("verigence.outcome", outcome)
                        if result.error_code:
                            span.set_attribute("verigence.error.code", result.error_code)
                        span.set_status(Status(StatusCode.ERROR, result.error_code or outcome))
                        record_processing_job(
                            outcome=outcome,
                            job_type=job_type,
                            duration_ms=total_ms,
                        )

                except Exception as exc:
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
                        attempt_no=attempt_no,
                        job_log=job_log,
                    )
                    total_ms = round((time.monotonic() - job_start) * 1000, 1)
                    outcome = "retry_pending" if attempt_no == 1 else "failed"
                    span.set_attribute("verigence.outcome", outcome)
                    span.set_attribute("verigence.error.code", "WORKER_INTERNAL_ERROR")
                    span.set_status(Status(StatusCode.ERROR, "WORKER_INTERNAL_ERROR"))
                    record_processing_job(
                        outcome=outcome,
                        job_type=job_type,
                        duration_ms=total_ms,
                    )

        return True


async def _handle_failure(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: str,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    processing_run_id: uuid.UUID | None,
    error_code: str | None,
    error_detail: str | None,
    retryable: bool,
    attempt_no: int,
    job_log: Any,
) -> None:
    """Route failure to RETRY_PENDING (attempt 1, retryable) or D24 backout path."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    error_class = "RETRYABLE" if retryable else "NON_RETRYABLE"

    if retryable and attempt_no == 1:
        async with session_factory() as session, session.begin():
            await retry_job(
                session,
                tenant_id=tenant_id,
                processing_job_id=job_id,
                document_id=document_id,
                error_code=error_code,
                error_detail=error_detail,
            )
        job_log.info(
            "job_retry_pending",
            error_class=error_class,
            error_code=error_code,
            error_detail=error_detail,
        )
        return

    settings = get_settings()
    ttl_hours: int = settings.backout_ttl_hours

    async with session_factory() as session, session.begin():
        await fail_job(
            session,
            tenant_id=tenant_id,
            processing_job_id=job_id,
            document_id=document_id,
            error_code=error_code,
            error_detail=error_detail,
        )
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


_worker = ProcessingWorker()


def get_worker() -> ProcessingWorker:
    """Return the module-level ProcessingWorker singleton."""
    return _worker

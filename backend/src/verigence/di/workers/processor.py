"""workers/processor.py — Async DI worker loops.

The legacy/V1 processing path remains sequential and unchanged in behaviour.
Document Capture V2 processing jobs are routed to a bounded worker pool so
extraction can start immediately after the hard classification gate and multiple
Booking documents can be extracted concurrently.

Both paths execute the same durable processing pipeline.  V2 only wraps the
configured adapter so the already-accepted byte-based V2 classification is reused
locally; extraction is delegated unchanged to the configured provider adapter.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.document_ai.adapter import DocumentAIAdapter, get_document_ai_adapter
from verigence.di.document_ai.v2_preclassified_adapter import V2PreclassifiedAdapter
from verigence.di.integrations.audit_core import get_audit_core_link_client
from verigence.di.repositories.audit_links import (
    claim_pending_audit_link,
    mark_audit_link_attempt,
)
from verigence.di.repositories.backout import insert_backout_job
from verigence.di.repositories.processing_jobs import (
    claim_next_non_v2_job,
    claim_next_v2_job,
    complete_job,
    fail_job,
    retry_job,
)
from verigence.di.settings import get_settings
from verigence.di.workers.job_runner import run_processing_job

logger = structlog.get_logger(__name__)

_NOTIFY_CHANNEL = "di_processing_jobs"
_V2_PROCESSING_CONCURRENCY = 4
_V2_FALLBACK_POLL_SECONDS = 0.5


def _default_worker_id(prefix: str = "processing") -> str:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"
    return f"{prefix}.{hostname}.{os.getpid()}"


def _asyncpg_url(url: str) -> str:
    return (
        url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )


class _NotifyWorker:
    """Common LISTEN/NOTIFY lifecycle for processing workers."""

    def __init__(self, *, task_name: str, worker_prefix: str) -> None:
        self._task_name = task_name
        self._worker_prefix = worker_prefix
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._notify_event = asyncio.Event()
        self._notify_conn: Any | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._notify_event.clear()
        self._task = asyncio.create_task(self._run(), name=self._task_name)
        logger.info(f"{self._task_name}_started")

    async def stop(self) -> None:
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
        logger.info(f"{self._task_name}_stopped")

    async def _open_notify_conn(self, notify_db_url: str) -> bool:
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
            logger.info("notify_received", channel=channel, payload=payload)
            self._notify_event.set()

        try:
            conn = await asyncpg.connect(_asyncpg_url(notify_db_url))
            await conn.add_listener(_NOTIFY_CHANNEL, _on_notify)
            self._notify_conn = conn
            logger.info(
                "notify_listener_started",
                channel=_NOTIFY_CHANNEL,
                worker=self._task_name,
            )
            return True
        except Exception as exc:
            logger.warning(
                "notify_listener_failed",
                reason=str(exc),
                fallback="poll_only",
                worker=self._task_name,
            )
            return False

    async def _run(self) -> None:  # pragma: no cover - abstract runtime loop
        raise NotImplementedError


class ProcessingWorker(_NotifyWorker):
    """Sequential legacy/V1 worker plus Audit-link delivery."""

    def __init__(self) -> None:
        super().__init__(task_name="processing-worker", worker_prefix="processing")

    async def _run(self) -> None:
        settings = get_settings()
        poll_interval: int = getattr(settings, "worker_poll_interval_seconds", 30)
        worker_id = getattr(settings, "worker_id", None) or _default_worker_id()
        notify_db_url: str = getattr(settings, "worker_notify_db_url", "") or ""

        engine = create_async_engine(str(settings.database_url), echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        ai_adapter = get_document_ai_adapter()
        log = logger.bind(worker_id=worker_id, processing_lane="legacy")

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
                    # Link delivery remains independent of extraction. One pending
                    # link per loop preserves the existing V1 behaviour.
                    did_work = await self._process_pending_audit_link(
                        session_factory=session_factory,
                        log=log,
                    )
                    if not did_work:
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

    async def _process_pending_audit_link(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        log: Any,
    ) -> bool:
        async with session_factory() as session, session.begin():
            link = await claim_pending_audit_link(session)
            if link is None:
                return False

            tenant_id = str(link["tenant_id"])
            document_id: uuid.UUID = link["document_id"]
            requirement_ref = str(link["audit_requirement_ref"])
            link_log = log.bind(
                tenant_id=tenant_id,
                document_id=str(document_id),
                audit_requirement_ref=requirement_ref,
            )
            try:
                await get_audit_core_link_client().link_booking_document(
                    requirement_ref=requirement_ref,
                    document_id=str(document_id),
                )
            except Exception as exc:
                await mark_audit_link_attempt(
                    session,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    acknowledged=False,
                    error_summary=f"{type(exc).__name__}: {exc}",
                )
                link_log.warning(
                    "audit_document_link_delivery_failed",
                    attempt=int(link["audit_link_attempt_count"]) + 1,
                    error_type=type(exc).__name__,
                )
            else:
                await mark_audit_link_attempt(
                    session,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    acknowledged=True,
                )
                link_log.info(
                    "audit_document_link_acknowledged",
                    attempt=int(link["audit_link_attempt_count"]) + 1,
                )
            return True

    async def _process_one(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        ai_adapter: DocumentAIAdapter,
        log: Any,
    ) -> bool:
        async with session_factory() as session:
            async with session.begin():
                job = await claim_next_non_v2_job(session, worker_id=worker_id)
            if job is None:
                return False

        await _execute_claimed_job(
            session_factory=session_factory,
            job=job,
            ai_adapter=ai_adapter,
            log=log,
        )
        return True


class V2ProcessingWorker(_NotifyWorker):
    """One lane of the bounded V2 extraction pool.

    A classified V2 document has already passed the Step-1 hard gate.  This lane
    claims only those jobs and reuses that accepted classification, so no second
    provider classification call is made.  The unchanged processing pipeline then
    performs extraction, normalization, validation, lineage and scoring.
    """

    def __init__(self, slot: int) -> None:
        self._slot = slot
        super().__init__(
            task_name=f"v2-processing-worker-{slot}",
            worker_prefix=f"v2-processing-{slot}",
        )

    async def _run(self) -> None:
        settings = get_settings()
        worker_id = _default_worker_id(self._worker_prefix)
        notify_db_url: str = getattr(settings, "worker_notify_db_url", "") or ""
        engine = create_async_engine(str(settings.database_url), echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        delegate = get_document_ai_adapter()
        log = logger.bind(
            worker_id=worker_id,
            processing_lane="capture_v2",
            pool_slot=self._slot,
        )

        notify_active = False
        if notify_db_url.strip():
            notify_active = await self._open_notify_conn(notify_db_url)
        if not notify_active:
            log.info(
                "v2_notify_listener_fallback",
                poll_interval_seconds=_V2_FALLBACK_POLL_SECONDS,
            )

        log.info(
            "v2_processing_worker_loop_started",
            notify_active=notify_active,
            fallback_poll_seconds=_V2_FALLBACK_POLL_SECONDS,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    did_work = await self._process_one(
                        session_factory=session_factory,
                        worker_id=worker_id,
                        delegate=delegate,
                        log=log,
                    )
                except Exception as exc:
                    log.exception("v2_processing_worker_loop_error", error=str(exc))
                    did_work = False

                if not did_work:
                    self._notify_event.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            asyncio.shield(self._notify_event.wait()),
                            timeout=_V2_FALLBACK_POLL_SECONDS,
                        )
        finally:
            await engine.dispose()

    async def _process_one(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        delegate: DocumentAIAdapter,
        log: Any,
    ) -> bool:
        async with session_factory() as session:
            async with session.begin():
                job = await claim_next_v2_job(session, worker_id=worker_id)
            if job is None:
                return False

        document_type_key = str(job["capture_v2_document_type_key"])
        raw_confidence = job["capture_v2_classification_confidence"]
        classification_confidence = (
            Decimal(str(raw_confidence)) if raw_confidence is not None else Decimal("0")
        )
        adapter = V2PreclassifiedAdapter(
            delegate,
            document_type_key=document_type_key,
            confidence=classification_confidence,
        )
        await _execute_claimed_job(
            session_factory=session_factory,
            job=job,
            ai_adapter=adapter,
            log=log.bind(
                capture_v2_document_type_key=document_type_key,
                capture_v2_classification_confidence=str(classification_confidence),
                classification_reused=True,
            ),
        )
        return True


async def _execute_claimed_job(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    job: dict[str, Any],
    ai_adapter: DocumentAIAdapter,
    log: Any,
) -> None:
    tenant_id: str = str(job["tenant_id"])
    job_id: uuid.UUID = job["processing_job_id"]
    document_id: uuid.UUID = job["document_id"]
    correlation_id: str = str(job["correlation_id"])
    job_type: str = str(job["job_type"])

    job_log = log.bind(
        tenant_id=tenant_id,
        document_id=str(document_id),
        processing_job_id=str(job_id),
        correlation_id=correlation_id,
        job_type=job_type,
    )
    job_log.info("job_claimed")

    job_start = time.monotonic()
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
                    attempt_no=int(job["attempt_no"]),
                    job_log=job_log,
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
                attempt_no=int(job["attempt_no"]),
                job_log=job_log,
            )


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
    from datetime import UTC, datetime

    from sqlalchemy import text

    error_class = "RETRYABLE" if retryable else "NON_RETRYABLE"

    if retryable and attempt_no == 1:
        async with session_factory() as session, session.begin():
            await retry_job(
                session,
                tenant_id=tenant_id,
                processing_job_id=job_id,
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


class ProcessingWorkerGroup:
    """One legacy lane plus a bounded V2 extraction pool."""

    def __init__(self, v2_concurrency: int = _V2_PROCESSING_CONCURRENCY) -> None:
        self._legacy = ProcessingWorker()
        self._v2 = [V2ProcessingWorker(slot + 1) for slot in range(v2_concurrency)]

    def start(self) -> None:
        self._legacy.start()
        for worker in self._v2:
            worker.start()
        logger.info(
            "processing_worker_group_started",
            v2_concurrency=len(self._v2),
        )

    async def stop(self) -> None:
        await asyncio.gather(
            self._legacy.stop(),
            *(worker.stop() for worker in self._v2),
        )
        logger.info("processing_worker_group_stopped")


_worker = ProcessingWorkerGroup()


def get_worker() -> ProcessingWorkerGroup:
    return _worker

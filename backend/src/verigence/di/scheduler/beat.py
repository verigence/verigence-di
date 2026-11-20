"""scheduler/beat.py — background job scheduler.

Runs two independent things in-process alongside the legacy worker, every 60
seconds:

  0. Reclaim stale RUNNING jobs (lease timeout exceeded).
  1. Sweep expired backout_jobs rows (D24).

Nothing here runs by the time of day.

  There is no once-daily retry (product owner, 20 Nov 2026: "remove" it). It
  gave a legacy (non-Capture-V2) document that failed once a second attempt at
  the Tenant's end-of-day time -- 23:00 UTC for every Tenant, 4:30 am India
  time, inside the night's sleep. Every document in DI is Capture V2, whose
  retries are scheduled by day (repositories.processing_jobs.
  schedule_v2_fast_retry); the last once-daily retry ran on 5 Sep 2026. A
  legacy document's failure is now final at once (workers.processor.
  _handle_failure). tenant_settings.eod_retry_local_time and
  eod_retry_enabled are still stored and returned by the Tenant configuration
  API, and are read by nothing.

  There is no nightly reprocessing (product owner, 2026-10-22): nothing is
  processed at night. The run that gave every FAILED document more tries at
  17:00 UTC (and queued reading for classified pages that never got a job, and
  the night re-read of a page our setup refused) is gone with its Audit Core
  status report. A document that ended FAILED stays FAILED; Audit Core raises
  the PC's "Document to resubmit" task and the PC uploads it again.

Design:
- APScheduler AsyncIOScheduler runs in-process, every 60 seconds
- It does nothing while the worker rests at night (verigence.di.night_rest)

Lifecycle:
  start() — called by the legacy worker process (and FastAPI lifespan when
            the API runs its own worker)
  stop()  — called on shutdown
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.night_rest import resting as worker_resting
from verigence.di.repositories.backout import insert_backout_job, sweep_expired_backout_jobs
from verigence.di.repositories.processing_jobs import fail_job
from verigence.di.runtime_errors import (
    safe_exception_context,
    safe_persisted_detail,
)

logger = structlog.get_logger(__name__)

# An expired RUNNING processing job is put back to PENDING at most this many
# times; the next expiry fails it, so a document that kills the worker every
# time stops being retried.
_MAX_LEASE_RECLAIMS = 2
# A Capture V2 job is reclaimed at most once (product owner's rule
# 2026-10-20): a worker dying mid-job is a technical failure, and a technical
# failure gets two runs in all, never a third.
_V2_MAX_LEASE_RECLAIMS = 1
_LEASE_EXHAUSTED_CODE = "WORKER_LEASE_EXHAUSTED"


class EODRetryScheduler:
    """APScheduler-backed background job scheduler (name kept for
    call-site compatibility)."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        """Start the APScheduler. Called once from FastAPI lifespan."""
        from verigence.di.settings import get_settings
        settings = get_settings()

        engine = create_async_engine(str(settings.database_url), echo=False)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            _run_scheduler_tick,
            trigger="interval",
            seconds=60,
            kwargs={"session_factory": session_factory},
            id="scheduler_tick",
            name="Background Job Scheduler",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("scheduler_started", interval_seconds=60)

    def stop(self) -> None:
        """Shut down the APScheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


async def _run_scheduler_tick(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Periodic check (every 60 s) -- see module docstring for the two
    independent things this does."""
    # The night's sleep (verigence.di.night_rest): a resting worker asks the
    # database nothing. Nothing is running that could go stale.
    if worker_resting():
        return
    now_utc = datetime.now(UTC)
    tick_correlation_id = f"scheduler.{uuid.uuid4()}"
    with structlog.contextvars.bound_contextvars(correlation_id=tick_correlation_id):
        await _run_scheduler_tick_in_context(session_factory, now_utc)


async def _run_scheduler_tick_in_context(
    session_factory: async_sessionmaker[AsyncSession],
    now_utc: datetime,
) -> None:
    log = logger.bind(scheduled_at_utc=now_utc.isoformat())
    log.debug("scheduler_tick")

    # ── 0. Stale RUNNING job reaper ──────────────────────────────────────
    try:
        async with session_factory() as session, session.begin():
            await _reclaim_stale_jobs(session, now_utc, log=log)
    except Exception as exc:
        log.warning("stale_job_reaper_failed", **safe_exception_context(exc))
    try:
        async with session_factory() as session, session.begin():
            await _reclaim_stale_classification_jobs(session, now_utc, log=log)
    except Exception as exc:
        log.warning("stale_classification_job_reaper_failed", **safe_exception_context(exc))

    # ── 1. Backout sweep — runs on every tick regardless of any window ──────
    try:
        async with session_factory() as session, session.begin():
            deleted = await sweep_expired_backout_jobs(session)
        if deleted:
            log.info("backout_sweep_completed", rows_deleted=deleted)
    except Exception as exc:
        log.warning("backout_sweep_failed", **safe_exception_context(exc))



async def _reclaim_stale_jobs(
    session: AsyncSession, now_utc: datetime, *, log: Any = logger,
) -> int:
    """Handle RUNNING processing jobs whose lease has expired.

    Each is put back to PENDING with lease_reclaim_count incremented, until it
    has been reclaimed _MAX_LEASE_RECLAIMS times; the next expiry fails it
    through the normal failure path (job + document FAILED, backout row) so
    a job that kills the worker every time eventually stops.

    Uses worker_lease_timeout_minutes from settings (default 10).
    Returns the number of jobs reclaimed or failed.
    """
    from verigence.di.settings import get_settings
    settings = get_settings()
    lease_minutes = getattr(settings, "worker_lease_timeout_minutes", 10)
    rows = (
        await session.execute(
            text("""
                SELECT pj.tenant_id, pj.processing_job_id, pj.document_id, pj.job_type,
                       pj.attempt_no, pj.lease_reclaim_count,
                       EXISTS (
                           SELECT 1 FROM docintel.document_capture_v2_uploads v2
                           WHERE v2.tenant_id = pj.tenant_id AND v2.document_id = pj.document_id
                       ) AS is_capture_v2
                FROM docintel.processing_jobs pj
                WHERE job_status = 'RUNNING'
                  AND locked_at_utc < :cutoff
                ORDER BY locked_at_utc
                FOR UPDATE SKIP LOCKED
            """),
            {"cutoff": now_utc - timedelta(minutes=lease_minutes)},
        )
    ).mappings().all()
    if not rows:
        return 0

    reset: list[str] = []
    exhausted: list[str] = []
    for row in rows:
        job_id = str(row["processing_job_id"])
        limit = _V2_MAX_LEASE_RECLAIMS if row.get("is_capture_v2") else _MAX_LEASE_RECLAIMS
        if int(row["lease_reclaim_count"]) >= limit:
            detail = safe_persisted_detail(_LEASE_EXHAUSTED_CODE)
            await fail_job(
                session,
                tenant_id=row["tenant_id"],
                processing_job_id=row["processing_job_id"],
                document_id=row["document_id"],
                error_code=_LEASE_EXHAUSTED_CODE,
                error_detail=detail,
            )
            await insert_backout_job(
                session,
                tenant_id=row["tenant_id"],
                document_id=row["document_id"],
                processing_job_id=row["processing_job_id"],
                processing_run_id=None,
                error_class="NON_RETRYABLE",
                error_code=_LEASE_EXHAUSTED_CODE,
                error_detail=detail,
                ttl_hours=settings.backout_ttl_hours,
            )
            exhausted.append(job_id)
        else:
            await session.execute(
                text("""
                    UPDATE docintel.processing_jobs
                    SET job_status = 'PENDING',
                        locked_by = NULL,
                        locked_at_utc = NULL,
                        lease_reclaim_count = lease_reclaim_count + 1
                    WHERE tenant_id = :tenant_id
                      AND processing_job_id = :job_id
                """),
                {"tenant_id": row["tenant_id"], "job_id": row["processing_job_id"]},
            )
            reset.append(job_id)

    if reset:
        log.warning(
            "stale_running_job_reset",
            count=len(reset),
            processing_job_ids=reset,
            lease_timeout_minutes=lease_minutes,
        )
    if exhausted:
        log.error(
            "stale_running_job_abandoned",
            count=len(exhausted),
            processing_job_ids=exhausted,
            error_code=_LEASE_EXHAUSTED_CODE,
            error_category="TECHNICAL",
            max_lease_reclaims=_MAX_LEASE_RECLAIMS,
        )
    return len(rows)


async def _reclaim_stale_classification_jobs(
    session: AsyncSession, now_utc: datetime, *, log: Any = logger,
) -> int:
    """Handle RUNNING Capture V2 classification jobs whose lease has expired.

    Mirrors the classification worker's own failure handling: the attempt
    counter is incremented and the upload goes back from CLASSIFYING to
    STORED for another attempt; once the attempts are used up, job and upload
    are FAILED with CLASSIFICATION_FAILED.
    """
    from verigence.di.settings import get_settings
    from verigence.di.workers.capture_v2_classifier import CLASSIFICATION_MAX_ATTEMPTS

    lease_minutes = getattr(get_settings(), "worker_lease_timeout_minutes", 10)
    rows = (
        await session.execute(
            text("""
                SELECT tenant_id, classification_job_id, document_id, attempt_no
                FROM docintel.document_capture_v2_classification_jobs
                WHERE job_status = 'RUNNING'
                  AND locked_at_utc < :cutoff
                ORDER BY locked_at_utc
                FOR UPDATE SKIP LOCKED
            """),
            {"cutoff": now_utc - timedelta(minutes=lease_minutes)},
        )
    ).mappings().all()
    if not rows:
        return 0

    retried: list[str] = []
    failed: list[str] = []
    for row in rows:
        params = {
            "tenant_id": row["tenant_id"],
            "job_id": row["classification_job_id"],
            "document_id": row["document_id"],
            "now": now_utc,
        }
        if int(row["attempt_no"]) < CLASSIFICATION_MAX_ATTEMPTS:
            await session.execute(
                text("""
                    UPDATE docintel.document_capture_v2_classification_jobs
                    SET job_status = 'PENDING', attempt_no = attempt_no + 1,
                        due_at_utc = :now, locked_by = NULL, locked_at_utc = NULL,
                        error_code = 'CLASSIFICATION_RETRY', error_detail = :detail,
                        updated_at_utc = :now
                    WHERE tenant_id = :tenant_id AND classification_job_id = :job_id
                """),
                {**params, "detail": safe_persisted_detail("CLASSIFICATION_RETRY")},
            )
            await session.execute(
                text("""
                    UPDATE docintel.document_capture_v2_uploads
                    SET state = 'STORED', updated_at_utc = :now
                    WHERE tenant_id = :tenant_id AND document_id = :document_id
                      AND state = 'CLASSIFYING'
                """),
                params,
            )
            retried.append(str(row["classification_job_id"]))
        else:
            detail = safe_persisted_detail("CLASSIFICATION_FAILED")
            await session.execute(
                text("""
                    UPDATE docintel.document_capture_v2_classification_jobs
                    SET job_status = 'FAILED', completed_at_utc = :now,
                        locked_by = NULL, locked_at_utc = NULL,
                        error_code = 'CLASSIFICATION_FAILED', error_detail = :detail,
                        updated_at_utc = :now
                    WHERE tenant_id = :tenant_id AND classification_job_id = :job_id
                """),
                {**params, "detail": detail},
            )
            await session.execute(
                text("""
                    UPDATE docintel.document_capture_v2_uploads
                    SET state = 'FAILED', failure_code = 'CLASSIFICATION_FAILED',
                        failure_detail = :detail, updated_at_utc = :now
                    WHERE tenant_id = :tenant_id AND document_id = :document_id
                      AND state IN ('STORED', 'CLASSIFYING')
                """),
                {**params, "detail": detail},
            )
            failed.append(str(row["classification_job_id"]))

    if retried:
        log.warning(
            "stale_classification_job_reset",
            count=len(retried),
            classification_job_ids=retried,
            lease_timeout_minutes=lease_minutes,
        )
    if failed:
        log.error(
            "stale_classification_job_failed",
            count=len(failed),
            classification_job_ids=failed,
            error_code="CLASSIFICATION_FAILED",
            error_category="TECHNICAL",
        )
    return len(rows)


# ── Module-level singleton ────────────────────────────────────────────────────

_scheduler = EODRetryScheduler()


def get_eod_scheduler() -> EODRetryScheduler:
    """Return the module-level EODRetryScheduler singleton."""
    return _scheduler

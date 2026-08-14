"""scheduler/beat.py — EOD Retry Scheduler.

Implements DI_LLD_v2.2 §EOD Retry Scheduler:

  At each Tenant's configured local EOD time:
  1. Select RETRY_PENDING Documents with no existing EOD_RETRY job
  2. Insert one EOD_RETRY processing job (attempt_no=2)
  3. The Processing Worker picks these up on the next poll

Design:
- APScheduler AsyncIOScheduler runs in-process alongside FastAPI
- Runs every 60 seconds; uses per-Tenant timezone + eod_retry_local_time to decide
  whether EOD has just passed (within the scheduling window)
- Idempotent: the UNIQUE (tenant_id, document_id, job_type) constraint prevents duplicates

Configuration (from tenant_settings):
  timezone_name          — e.g. "Africa/Johannesburg"
  eod_retry_local_time   — e.g. 18:00:00
  eod_retry_enabled      — boolean, must be true

Lifecycle:
  start(app) — called from FastAPI lifespan
  stop()     — called from FastAPI lifespan shutdown
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.repositories.backout import sweep_expired_backout_jobs

logger = structlog.get_logger(__name__)

# How many seconds around the EOD window we consider "just passed"
# (scheduler fires every 60s; ±90s window prevents both double-fire and misses)
_EOD_WINDOW_SECONDS = 90


class EODRetryScheduler:
    """APScheduler-backed EOD retry job injector."""

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
            _run_eod_check,
            trigger="interval",
            seconds=60,
            kwargs={"session_factory": session_factory},
            id="eod_retry_check",
            name="EOD Retry Scheduler",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info("eod_retry_scheduler_started", interval_seconds=60)

    def stop(self) -> None:
        """Shut down the APScheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("eod_retry_scheduler_stopped")


async def _run_eod_check(session_factory: async_sessionmaker) -> None:
    """Periodic check (every 60 s):
    1. Sweep expired backout_jobs rows (D24) — runs on every tick.
    2. For every enabled Tenant, insert EOD_RETRY jobs if EOD just passed.
    """
    now_utc = datetime.now(UTC)
    log = logger.bind(scheduled_at_utc=now_utc.isoformat())

    # ── 1. Backout sweep — runs on every tick regardless of EOD window ────────
    try:
        async with session_factory() as session, session.begin():
            deleted = await sweep_expired_backout_jobs(session)
        if deleted:
            log.info("backout_sweep_completed", rows_deleted=deleted)
    except Exception as exc:
        log.warning("backout_sweep_failed", error=str(exc))

    # ── 2. EOD retry job injection — only when Tenant EOD window matches ──────
    async with session_factory() as session:
        tenants = await _load_enabled_tenants(session)

    for tenant in tenants:
        tenant_id: str = tenant["tenant_id"]
        tz_name: str = tenant["timezone_name"]
        eod_time: dtime = tenant["eod_retry_local_time"]

        if not _is_eod_window(now_utc, tz_name, eod_time):
            continue

        log.info("eod_window_matched", tenant_id=tenant_id, timezone=tz_name)
        async with session_factory() as session, session.begin():
            count = await _insert_eod_retry_jobs(session, tenant_id, now_utc)
        if count:
            log.info("eod_retry_jobs_inserted",
                     tenant_id=tenant_id,
                     jobs_inserted=count)


async def _load_enabled_tenants(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("""
                SELECT tenant_id, timezone_name, eod_retry_local_time
                FROM docintel.tenant_settings
                WHERE status = 'ACTIVE'
                  AND eod_retry_enabled = true
            """),
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def _is_eod_window(now_utc: datetime, tz_name: str, eod_time: dtime) -> bool:
    """Return True when local EOD time falls within the ±_EOD_WINDOW_SECONDS window."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except (ImportError, Exception):
        try:
            from dateutil import tz as dateutil_tz  # type: ignore[import]
            tz_obj = dateutil_tz.gettz(tz_name)
            if tz_obj is None:
                logger.warning("unknown_timezone", tz_name=tz_name)
                return False
            local_now = now_utc.astimezone(tz_obj)
        except Exception:
            logger.warning("timezone_conversion_failed", tz_name=tz_name)
            return False
    else:
        local_now = now_utc.astimezone(tz)

    # Convert both times to seconds since midnight for comparison
    local_seconds = (
        local_now.hour * 3600 + local_now.minute * 60 + local_now.second
    )
    eod_seconds = eod_time.hour * 3600 + eod_time.minute * 60 + eod_time.second

    return abs(local_seconds - eod_seconds) <= _EOD_WINDOW_SECONDS


async def _insert_eod_retry_jobs(
    session: AsyncSession,
    tenant_id: str,
    now_utc: datetime,
) -> int:
    """Insert one EOD_RETRY job for each eligible RETRY_PENDING document.

    Eligible = upload_status='FIT', processing_status='RETRY_PENDING',
               no existing EOD_RETRY job.

    Returns the number of jobs inserted.
    """
    # Find eligible documents (no EOD_RETRY job already exists)
    eligible_rows = (
        await session.execute(
            text("""
                SELECT d.document_id,
                       COALESCE(
                           (SELECT pj2.correlation_id
                            FROM docintel.processing_jobs pj2
                            WHERE pj2.tenant_id = d.tenant_id
                              AND pj2.document_id = d.document_id
                              AND pj2.job_type = 'INITIAL'
                            ORDER BY pj2.created_at_utc DESC
                            LIMIT 1),
                           gen_random_uuid()::text
                       ) AS original_correlation_id
                FROM docintel.documents d
                WHERE d.tenant_id = :tid
                  AND d.upload_status = 'FIT'
                  AND d.processing_status = 'RETRY_PENDING'
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.processing_jobs pj
                      WHERE pj.tenant_id = d.tenant_id
                        AND pj.document_id = d.document_id
                        AND pj.job_type = 'EOD_RETRY'
                  )
            """),
            {"tid": tenant_id},
        )
    ).all()

    count = 0
    for row in eligible_rows:
        doc_id = row[0]
        correlation_id = f"eod.{uuid.uuid4()}"

        try:
            await session.execute(
                text("""
                    INSERT INTO docintel.processing_jobs
                        (tenant_id, processing_job_id, document_id, correlation_id,
                         job_type, job_status, due_at_utc, attempt_no, created_at_utc)
                    VALUES
                        (:tid, :job_id, :doc_id, :corr,
                         'EOD_RETRY', 'PENDING', :now, 2, :now)
                    ON CONFLICT (tenant_id, document_id, job_type) DO NOTHING
                """),
                {
                    "tid": tenant_id,
                    "job_id": uuid.uuid4(),
                    "doc_id": doc_id,
                    "corr": correlation_id,
                    "now": now_utc,
                },
            )
            count += 1
        except Exception as exc:
            logger.warning("eod_retry_job_insert_failed",
                           tenant_id=tenant_id,
                           document_id=str(doc_id),
                           error=str(exc))

    return count


# ── Module-level singleton ────────────────────────────────────────────────────

_scheduler = EODRetryScheduler()


def get_eod_scheduler() -> EODRetryScheduler:
    """Return the module-level EODRetryScheduler singleton."""
    return _scheduler

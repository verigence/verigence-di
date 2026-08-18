"""repositories/backout.py — Backout queue repository (D24).

The backout queue is a dead-letter store for documents that fail processing.
Any failure (retryable or non-retryable) results in:
  1. Document set to FAILED / NOT_CONFIRMED
  2. Processing job set to FAILED
  3. One backout_jobs row inserted with expires_at_utc = NOW() + ttl_hours

A sweeper (called from EODRetryScheduler on every tick) hard-deletes expired
rows. No reprocessing is triggered from the backout queue.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_backout_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    processing_run_id: uuid.UUID | None,
    error_class: str,          # 'RETRYABLE' or 'NON_RETRYABLE'
    error_code: str | None,
    error_detail: str | None,
    ttl_hours: int = 12,
) -> uuid.UUID:
    """Insert one backout_jobs row for a failed document.

    Uses ON CONFLICT DO UPDATE so that if a document fails again (e.g. on
    a second attempt) the backout row is refreshed with the latest error and
    a new TTL rather than raising a unique-constraint error.

    Returns the backout_job_id.
    """
    backout_job_id = uuid.uuid4()
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=ttl_hours)

    await session.execute(
        text("""
            INSERT INTO docintel.backout_jobs
                (tenant_id, backout_job_id, document_id, processing_job_id,
                 processing_run_id, error_class, error_code, error_detail,
                 expires_at_utc, created_at_utc)
            VALUES
                (:tid, :bjid, :doc_id, :job_id,
                 :run_id, :error_class, :error_code, :error_detail,
                 :expires_at, :now)
            ON CONFLICT (tenant_id, document_id) DO UPDATE
                SET backout_job_id    = EXCLUDED.backout_job_id,
                    processing_job_id = EXCLUDED.processing_job_id,
                    processing_run_id = EXCLUDED.processing_run_id,
                    error_class       = EXCLUDED.error_class,
                    error_code        = EXCLUDED.error_code,
                    error_detail      = EXCLUDED.error_detail,
                    expires_at_utc    = EXCLUDED.expires_at_utc,
                    created_at_utc    = EXCLUDED.created_at_utc
        """),
        {
            "tid": tenant_id,
            "bjid": backout_job_id,
            "doc_id": document_id,
            "job_id": processing_job_id,
            "run_id": processing_run_id,
            "error_class": error_class,
            "error_code": error_code,
            "error_detail": error_detail,
            "expires_at": expires_at,
            "now": now,
        },
    )
    return backout_job_id


async def sweep_expired_backout_jobs(session: AsyncSession) -> int:
    """Hard-delete all backout_jobs rows whose TTL has expired.

    Called on every EODRetryScheduler tick (every 60 s). The document row is
    NOT touched — it remains FAILED / NOT_CONFIRMED after the backout entry
    is purged.

    Returns the number of rows deleted.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        text("""
            DELETE FROM docintel.backout_jobs
            WHERE expires_at_utc <= :now
        """),
        {"now": now},
    )
    return result.rowcount  # type: ignore[return-value]

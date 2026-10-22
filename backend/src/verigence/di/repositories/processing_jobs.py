"""repositories/processing_jobs.py — Processing job repository."""
from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.retry_policy import AI_RETRY_DELAYS_SECONDS
from verigence.di.runtime_errors import (
    safe_persisted_detail,
)

logger = structlog.get_logger(__name__)

_MAX_ERROR_DETAIL = 2000
_MAX_ERROR_CODE = 128

# The bounded V2 worker pool exists specifically to give Capture V2
# extraction a fast, PC-facing turnaround (see module docstring in
# workers/processor.py). Its retryable failures must not fall back to the
# legacy EOD Retry Scheduler, which can leave a document showing nothing
# more than "still processing" for up to ~24h (see schedule_v2_fast_retry
# below). How long each retry waits is retry_policy's (product owner's rule
# 2026-10-21: retried at T0+10 and T0+20 minutes); this is the wait when a
# caller does not say.
V2_FAST_RETRY_DELAY_SECONDS = AI_RETRY_DELAYS_SECONDS[0]


def _cap(value: str | None, limit: int) -> str | None:
    """Truncate a string to limit characters, or return None unchanged."""
    if value is None:
        return None
    return value[:limit]


async def create_initial_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    correlation_id: str,
) -> uuid.UUID:
    """Insert an INITIAL processing job for a FIT document.

    Returns the new processing_job_id.
    """
    job_id = uuid.uuid4()
    now = datetime.now(UTC)

    await session.execute(
        text("""
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id,
                 job_type, job_status, due_at_utc, attempt_no, created_at_utc)
            VALUES
                (:tenant_id, :job_id, :document_id, :correlation_id,
                 'INITIAL', 'PENDING', :now, 1, :now)
        """),
        {
            "tenant_id": tenant_id,
            "job_id": job_id,
            "document_id": document_id,
            "correlation_id": correlation_id,
            "now": now,
        },
    )
    return job_id


async def _claim_next_job(
    session: AsyncSession,
    *,
    worker_id: str,
    capture_v2_mode: str,
) -> dict | None:  # type: ignore[type-arg]
    """Claim one due processing job with optional V2 routing.

    ``capture_v2_mode`` is one of ``ANY``, ``ONLY`` or ``EXCLUDE``.  V2 routing
    is based on the durable Document Capture V2 row, not on a caller-provided
    flag.  This lets the normal worker remain sequential for legacy/V1 work while
    a bounded V2 worker pool can start extraction immediately after classification.
    """
    if capture_v2_mode not in {"ANY", "ONLY", "EXCLUDE"}:
        raise ValueError("capture_v2_mode must be ANY, ONLY or EXCLUDE")

    if capture_v2_mode == "ONLY":
        mode_clause = (
            "AND u.document_id IS NOT NULL "
            "AND u.state = 'CLASSIFIED' "
            "AND u.classified_document_type_key IS NOT NULL"
        )
    elif capture_v2_mode == "EXCLUDE":
        mode_clause = "AND u.document_id IS NULL"
    else:
        mode_clause = ""

    now = datetime.now(UTC)
    row = (
        await session.execute(
            text(
                f"""
                SELECT pj.tenant_id, pj.processing_job_id, pj.document_id,
                       pj.correlation_id, pj.job_type, pj.attempt_no,
                       u.classified_document_type_key AS capture_v2_document_type_key,
                       u.classification_confidence AS capture_v2_classification_confidence
                FROM docintel.processing_jobs pj
                LEFT JOIN docintel.document_capture_v2_uploads u
                  ON u.tenant_id = pj.tenant_id
                 AND u.document_id = pj.document_id
                WHERE pj.job_status = 'PENDING'
                  AND pj.due_at_utc <= :now
                  {mode_clause}
                ORDER BY pj.due_at_utc
                LIMIT 1
                FOR UPDATE OF pj SKIP LOCKED
                """
            ),
            {"now": now},
        )
    ).mappings().one_or_none()

    if row is None:
        return None

    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'RUNNING',
                locked_by = :worker_id,
                locked_at_utc = :now,
                started_at_utc = :now
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
        """),
        {
            "worker_id": worker_id,
            "now": now,
            "tenant_id": row["tenant_id"],
            "job_id": row["processing_job_id"],
        },
    )

    return {
        "tenant_id": row["tenant_id"],
        "processing_job_id": row["processing_job_id"],
        "document_id": row["document_id"],
        "correlation_id": row["correlation_id"],
        "job_type": row["job_type"],
        "attempt_no": row["attempt_no"],
        "capture_v2_document_type_key": row["capture_v2_document_type_key"],
        "capture_v2_classification_confidence": row[
            "capture_v2_classification_confidence"
        ],
    }


async def claim_next_job(
    session: AsyncSession,
    *,
    worker_id: str,
) -> dict | None:  # type: ignore[type-arg]
    """Backward-compatible claim of any PENDING due processing job."""
    return await _claim_next_job(
        session,
        worker_id=worker_id,
        capture_v2_mode="ANY",
    )


async def claim_next_non_v2_job(
    session: AsyncSession,
    *,
    worker_id: str,
) -> dict | None:  # type: ignore[type-arg]
    """Claim only legacy/V1 jobs; V2 jobs are reserved for the fast V2 pool."""
    return await _claim_next_job(
        session,
        worker_id=worker_id,
        capture_v2_mode="EXCLUDE",
    )


async def claim_next_v2_job(
    session: AsyncSession,
    *,
    worker_id: str,
) -> dict | None:  # type: ignore[type-arg]
    """Claim a classified Document Capture V2 processing job."""
    return await _claim_next_job(
        session,
        worker_id=worker_id,
        capture_v2_mode="ONLY",
    )


async def complete_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    processing_job_id: uuid.UUID,
    success: bool,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a processing job complete and redeliver the Audit link after success.

    The first Audit callback can happen immediately after upload so Audit Core can
    establish durable evidence linkage while extraction is still running.  When
    extraction succeeds, requeue that same durable callback. Audit Core then reads
    the confirmed DI facts, copies every field to its Core audit store, and applies
    the confidence-based PC review policy. Callback delivery remains retriable and
    never sits on the extraction critical path.
    """
    now = datetime.now(UTC)
    final_status = "COMPLETED" if success else "FAILED"
    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = :status,
                completed_at_utc = :now,
                error_code = :error_code,
                error_detail = :error_detail
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
        """),
        {
            "status": final_status,
            "now": now,
            "error_code": _cap(error_code, _MAX_ERROR_CODE),
            "error_detail": _cap(error_detail, _MAX_ERROR_DETAIL),
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
        },
    )

    if success:
        await session.execute(
            text("""
                UPDATE docintel.documents d
                SET audit_link_status = 'PENDING',
                    audit_link_last_attempt_at_utc = NULL,
                    audit_link_acknowledged_at_utc = NULL,
                    audit_link_last_error = NULL,
                    updated_at_utc = :now
                FROM docintel.processing_jobs pj
                WHERE pj.tenant_id = :tenant_id
                  AND pj.processing_job_id = :job_id
                  AND d.tenant_id = pj.tenant_id
                  AND d.document_id = pj.document_id
                  AND d.audit_requirement_ref IS NOT NULL
            """),
            {
                "now": now,
                "tenant_id": tenant_id,
                "job_id": processing_job_id,
            },
        )


async def retry_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    processing_job_id: uuid.UUID,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a RUNNING job as FAILED and set the document to RETRY_PENDING.

    Called by the worker after a RETRYABLE processing failure.
    The EOD Retry Scheduler will later insert an EOD_RETRY job (attempt_no=2).
    """
    now = datetime.now(UTC)
    safe_code = _cap(error_code, _MAX_ERROR_CODE)
    safe_detail = _cap(error_detail, _MAX_ERROR_DETAIL)

    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'FAILED',
                completed_at_utc = :now,
                error_code = :error_code,
                error_detail = :error_detail
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
        """),
        {
            "now": now,
            "error_code": safe_code,
            "error_detail": safe_detail,
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
        },
    )
    await session.execute(
        text("""
            UPDATE docintel.documents d
            SET processing_status = 'RETRY_PENDING',
                confirmation_status = 'PENDING',
                processing_failure_code = :error_code,
                processing_failure_detail = :error_detail,
                updated_at_utc = :now
            FROM docintel.processing_jobs pj
            WHERE pj.tenant_id = :tenant_id
              AND pj.processing_job_id = :job_id
              AND d.tenant_id = pj.tenant_id
              AND d.document_id = pj.document_id
        """),
        {
            "now": now,
            "error_code": safe_code,
            "error_detail": safe_detail,
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
        },
    )


async def schedule_v2_fast_retry(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    correlation_id: str,
    attempt_no: int = 2,
    delay_seconds: int = V2_FAST_RETRY_DELAY_SECONDS,
) -> None:
    """Give a Capture V2 document's retryable extraction failure its next
    daytime attempt (``attempt_no``, due in ``delay_seconds``) instead of the
    legacy EOD Retry Scheduler.

    retry_job() above already set the document to RETRY_PENDING -- correct
    for the legacy/V1 flow, where the EOD Retry Scheduler inserting the
    attempt_no=2 job once a day is an accepted design (see scheduler/beat.py).
    But Document Capture V2's whole reason for a dedicated bounded worker
    pool is a fast, PC-facing turnaround (see workers/processor.py's module
    docstring) -- leaving its retry on the same once-daily schedule can
    leave a document showing nothing more than "still processing" for up
    to ~24h with no way for a PC to tell it already failed once.

    Idempotent via the same (tenant_id, document_id, job_type, attempt_no)
    uniqueness EOD_RETRY also relies on -- a second
    failed attempt at the SAME job_type+attempt_no can't insert a
    duplicate, and by the time a genuinely new upload of the same
    document_id could exist, this row is long since resolved.
    """
    now = datetime.now(UTC)
    due_at = now + timedelta(seconds=delay_seconds)
    await session.execute(
        text("""
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id,
                 job_type, job_status, due_at_utc, attempt_no, created_at_utc)
            VALUES
                (:tenant_id, :job_id, :document_id, :correlation_id,
                 'V2_FAST_RETRY', 'PENDING', :due_at, :attempt_no, :now)
            ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
        """),
        {
            "tenant_id": tenant_id,
            "job_id": uuid.uuid4(),
            "document_id": document_id,
            "correlation_id": correlation_id,
            "due_at": due_at,
            "attempt_no": attempt_no,
            "now": now,
        },
    )


# A quota hit (429) during extraction is the burst's doing, not the
# document's: the job goes back in the queue for five minutes, spread a
# little, and the attempt is not counted. Once the job has been waiting on
# the quota for RATE_LIMIT_DEFER_MAX_SECONDS it counts like any other
# retryable failure (decision 2026-09-30: load is never a failure).
RATE_LIMITED_CODE = "DOCUMENT_AI_RATE_LIMITED"
RATE_LIMIT_DEFER_SECONDS = 300
RATE_LIMIT_DEFER_JITTER_SECONDS = 60
# Eight hours (decision 2026-10-01): a quota that is out for the day is
# waited for that long, then the attempt counts like any other retryable
# failure.
RATE_LIMIT_DEFER_MAX_SECONDS = 8 * 3600


async def defer_job_after_rate_limit(
    session: AsyncSession,
    *,
    tenant_id: str,
    processing_job_id: uuid.UUID,
) -> int | None:
    """Put a RUNNING job back in the queue after a quota hit, same attempt
    number, due in five minutes or so. The document keeps its PROCESSING
    status, so callers see it as still in hand. Returns the delay, or None
    when the job has been waiting on the quota for too long (the caller
    then records an ordinary retryable failure)."""
    now = datetime.now(UTC)
    delay = RATE_LIMIT_DEFER_SECONDS + random.randint(0, RATE_LIMIT_DEFER_JITTER_SECONDS)  # noqa: S311
    deferred = await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'PENDING',
                due_at_utc = :due,
                locked_by = NULL,
                locked_at_utc = NULL,
                started_at_utc = NULL,
                error_code = :error_code,
                error_detail = :error_detail
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
              AND job_status = 'RUNNING'
              AND created_at_utc > :oldest
            RETURNING processing_job_id
        """),
        {
            "due": now + timedelta(seconds=delay),
            "error_code": RATE_LIMITED_CODE,
            "error_detail": _cap(safe_persisted_detail(RATE_LIMITED_CODE), _MAX_ERROR_DETAIL),
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
            "oldest": now - timedelta(seconds=RATE_LIMIT_DEFER_MAX_SECONDS),
        },
    )
    return delay if deferred.scalar_one_or_none() is not None else None


# There is no nightly reprocessing (product owner, 2026-10-22): nothing is
# processed at night. A document that ended FAILED stays FAILED; Audit Core
# raises the PC's "Document to resubmit" task and the PC uploads it again.
# The NIGHTLY_REPROCESS job type stays valid in the database only for rows
# written before that date.


MANUAL_REREAD_JOB_TYPE = "MANUAL_REREAD"


async def request_manual_reread(
    session: AsyncSession, *, tenant_id: str, document_id: uuid.UUID, requested_by: str,
) -> dict[str, Any]:
    """Queue one more reading of a classified document DI already holds,
    at a person's request (Audit Core's "Read again", decision 2026-10-01).
    Never re-uploads, never re-classifies. Outcomes:

      not_found          no such document for the tenant
      not_classified     DI has not (or could not) classified it yet
      already_processed  the document was read; the caller syncs instead
      in_progress        a job is already pending or running
      queued             a job was inserted (processingJobId returned)
    """
    row = (
        await session.execute(
            text("""
                SELECT d.processing_status, d.correlation_id,
                       u.state AS capture_state, u.classified_document_type_key,
                       (SELECT COUNT(*) FROM docintel.processing_jobs a
                         WHERE a.tenant_id = d.tenant_id AND a.document_id = d.document_id
                           AND a.job_status IN ('PENDING', 'RUNNING')) AS active_jobs,
                       (SELECT MAX(attempt_no) FROM docintel.processing_jobs b
                         WHERE b.tenant_id = d.tenant_id AND b.document_id = d.document_id) AS last_attempt
                FROM docintel.documents d
                LEFT JOIN docintel.document_capture_v2_uploads u
                  ON u.tenant_id = d.tenant_id AND u.document_id = d.document_id
                WHERE d.tenant_id = :tenant_id AND d.document_id = :document_id
            """),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return {"outcome": "not_found"}
    if row["capture_state"] != "CLASSIFIED" or not row["classified_document_type_key"]:
        return {"outcome": "not_classified", "captureState": row["capture_state"]}
    if row["processing_status"] == "PROCESSED":
        return {"outcome": "already_processed"}
    if int(row["active_jobs"] or 0) > 0:
        return {"outcome": "in_progress"}

    last_attempt = row["last_attempt"]
    if last_attempt is None:
        job_type, attempt_no = "INITIAL", 1
    else:
        job_type, attempt_no = MANUAL_REREAD_JOB_TYPE, max(int(last_attempt) + 1, 2)
    job_id = uuid.uuid4()
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id,
                 job_type, job_status, due_at_utc, attempt_no, created_at_utc)
            VALUES
                (:tenant_id, :job_id, :document_id, :corr, :job_type, 'PENDING', :now, :attempt_no, :now)
        """),
        {
            "tenant_id": tenant_id,
            "job_id": job_id,
            "document_id": document_id,
            "corr": row["correlation_id"] or f"reread.{uuid.uuid4()}",
            "job_type": job_type,
            "attempt_no": attempt_no,
            "now": now,
        },
    )
    await session.execute(
        text("SELECT pg_notify('di_processing_jobs', :payload)"), {"payload": str(job_id)},
    )
    logger.info(
        "manual_reread_queued",
        tenant_id=tenant_id,
        document_id=str(document_id),
        processing_job_id=str(job_id),
        job_type=job_type,
        attempt_no=attempt_no,
        requested_by=requested_by,
    )
    return {"outcome": "queued", "processingJobId": str(job_id), "jobType": job_type, "attemptNo": attempt_no}


SUPERSEDED_ERROR_CODE = "SUPERSEDED_ALREADY_PROCESSED"


async def document_processing_status(
    session: AsyncSession, *, tenant_id: str, document_id: uuid.UUID,
) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT processing_status FROM docintel.documents "
                "WHERE tenant_id = :tenant_id AND document_id = :document_id"
            ),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
    ).scalar_one_or_none()


async def cancel_superseded_job(
    session: AsyncSession, *, tenant_id: str, processing_job_id: uuid.UUID,
) -> None:
    """A retry/reprocess job whose document another attempt already
    PROCESSED: nothing to do, and re-running it would put a CONFIRMED
    document back into PROCESSING (ck_documents_confirmation_invariants)."""
    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'CANCELLED',
                completed_at_utc = :now,
                error_code = :error_code,
                error_detail = 'The document was already processed by another attempt.'
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
              AND job_status IN ('PENDING', 'RUNNING')
        """),
        {"now": datetime.now(UTC), "error_code": SUPERSEDED_ERROR_CODE,
         "tenant_id": tenant_id, "job_id": processing_job_id},
    )


async def close_job_after_handler_error(
    session: AsyncSession, *, tenant_id: str, processing_job_id: uuid.UUID, error_code: str,
) -> None:
    """Last resort when recording a failure itself failed: close the job
    so the stale-job reaper does not re-run it every lease period."""
    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'FAILED',
                completed_at_utc = :now,
                error_code = :error_code,
                error_detail = 'Recording the processing failure failed; see worker logs.'
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
              AND job_status = 'RUNNING'
        """),
        {"now": datetime.now(UTC), "error_code": _cap(error_code, _MAX_ERROR_CODE),
         "tenant_id": tenant_id, "job_id": processing_job_id},
    )


async def fail_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    processing_job_id: uuid.UUID,
    document_id: uuid.UUID,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a RUNNING job FAILED and the document FAILED/NOT_CONFIRMED.

    Called by the worker after a NON_RETRYABLE processing failure.
    """
    now = datetime.now(UTC)
    safe_code = _cap(error_code, _MAX_ERROR_CODE)
    safe_detail = _cap(error_detail, _MAX_ERROR_DETAIL)

    await session.execute(
        text("""
            UPDATE docintel.processing_jobs
            SET job_status = 'FAILED',
                completed_at_utc = :now,
                error_code = :error_code,
                error_detail = :error_detail
            WHERE tenant_id = :tenant_id
              AND processing_job_id = :job_id
        """),
        {
            "now": now,
            "error_code": safe_code,
            "error_detail": safe_detail,
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
        },
    )
    # A job that fails for a document another attempt already PROCESSED
    # must not demote it: FAILED with that attempt's scores violates
    # ck_documents_confirmation_invariants, and the failure handler itself
    # raising left the job RUNNING for the stale-job reaper to retry forever.
    await session.execute(
        text("""
            UPDATE docintel.documents
            SET processing_status = 'FAILED',
                confirmation_status = 'NOT_CONFIRMED',
                processing_failure_code = :error_code,
                processing_failure_detail = :error_detail,
                updated_at_utc = :now
            WHERE tenant_id = :tenant_id
              AND document_id = :doc_id
              AND processing_status <> 'PROCESSED'
        """),
        {
            "now": now,
            "error_code": safe_code,
            "error_detail": safe_detail,
            "tenant_id": tenant_id,
            "doc_id": document_id,
        },
    )
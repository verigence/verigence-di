"""repositories/processing_jobs.py — Processing job repository."""
from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.runtime_errors import (
    BUSINESS_FAILURE_CODES,
    CONFIGURATION_FAILURE_CODES,
    safe_exception_context,
    safe_persisted_detail,
)

logger = structlog.get_logger(__name__)

_MAX_ERROR_DETAIL = 2000
_MAX_ERROR_CODE = 128

# The bounded V2 worker pool exists specifically to give Capture V2
# extraction a fast, PC-facing turnaround (see module docstring in
# workers/processor.py). Its first retryable failure must not fall back to
# the legacy EOD Retry Scheduler, which can leave a document showing
# nothing more than "still processing" for up to ~24h (see
# schedule_v2_fast_retry below).
# Five minutes (decision 2026-09-30): no request is retried within five
# minutes, so the fast second attempt waits that long.
V2_FAST_RETRY_DELAY_SECONDS = 300


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
) -> None:
    """Give a Capture V2 document's first retryable extraction failure a
    fast second attempt instead of the legacy EOD Retry Scheduler.

    retry_job() above already set the document to RETRY_PENDING -- correct
    for the legacy/V1 flow, where the EOD Retry Scheduler inserting the
    attempt_no=2 job once a day is an accepted design (see scheduler/beat.py).
    But Document Capture V2's whole reason for a dedicated bounded worker
    pool is a fast, PC-facing turnaround (see workers/processor.py's module
    docstring) -- leaving its retry on the same once-daily schedule can
    leave a document showing nothing more than "still processing" for up
    to ~24h with no way for a PC to tell it already failed once.

    Idempotent via the same (tenant_id, document_id, job_type, attempt_no)
    uniqueness EOD_RETRY and NIGHTLY_REPROCESS also rely on -- a second
    failed attempt at the SAME job_type+attempt_no can't insert a
    duplicate, and by the time a genuinely new upload of the same
    document_id could exist, this row is long since resolved.
    """
    now = datetime.now(UTC)
    due_at = now + timedelta(seconds=V2_FAST_RETRY_DELAY_SECONDS)
    await session.execute(
        text("""
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id,
                 job_type, job_status, due_at_utc, attempt_no, created_at_utc)
            VALUES
                (:tenant_id, :job_id, :document_id, :correlation_id,
                 'V2_FAST_RETRY', 'PENDING', :due_at, 2, :now)
            ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
        """),
        {
            "tenant_id": tenant_id,
            "job_id": uuid.uuid4(),
            "document_id": document_id,
            "correlation_id": correlation_id,
            "due_at": due_at,
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
# waited for until the night, when the nightly run takes over.
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


NIGHTLY_REPROCESS_MAX_ATTEMPTS = 3
_NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO = 3  # 1=INITIAL, 2=EOD_RETRY/V2_FAST_RETRY, 3.. = nightly

# A document gets at most one nightly attempt per night. The trigger window
# spans several ticks, so an attempt that fails within it must not be
# re-queued by the next tick; 20h is comfortably shorter than a day and
# longer than any window.
NIGHTLY_REPROCESS_MIN_INTERVAL = timedelta(hours=20)

# Failures a re-run cannot change: the document's own outcome (ambiguous,
# unreadable, blank, unsupported, blocked), a configuration gap an admin must
# fix, or a document that repeatedly killed the worker.
NIGHTLY_NON_REPROCESSABLE_CODES = frozenset(
    BUSINESS_FAILURE_CODES | CONFIGURATION_FAILURE_CODES | {"WORKER_LEASE_EXHAUSTED"}
)


async def insert_nightly_reprocessing_jobs(
    session: AsyncSession,
) -> int:
    """Give every currently-FAILED document (any active Tenant) one more
    extraction attempt, up to NIGHTLY_REPROCESS_MAX_ATTEMPTS total nightly
    tries -- called once nightly by scheduler/beat.py, not per-Tenant (see
    its own module docstring: one fixed global trigger time, not each
    Tenant's own local EOD).

    A document already sitting on its NIGHTLY_REPROCESS_MAX_ATTEMPTS-th
    attempt (or beyond, if the count were ever exceeded some other way) is
    left alone -- it stays FAILED, its backout_jobs row is its permanent
    record, and no further reprocessing job is ever queued for it again.

    Returns the number of jobs inserted (i.e. documents queued for another
    attempt tonight).
    """
    now = datetime.now(UTC)
    eligible_rows = (
        await session.execute(
            text("""
                SELECT d.tenant_id, d.document_id,
                       COALESCE(
                           (SELECT max(pj.attempt_no)
                            FROM docintel.processing_jobs pj
                            WHERE pj.tenant_id = d.tenant_id
                              AND pj.document_id = d.document_id
                              AND pj.job_type = 'NIGHTLY_REPROCESS'),
                           :first_attempt_no - 1
                       ) AS last_attempt_no,
                       COALESCE(
                           (SELECT pj2.correlation_id
                            FROM docintel.processing_jobs pj2
                            WHERE pj2.tenant_id = d.tenant_id
                              AND pj2.document_id = d.document_id
                              AND pj2.job_type = 'INITIAL'
                            ORDER BY pj2.created_at_utc DESC
                            LIMIT 1),
                           d.correlation_id
                       ) AS original_correlation_id
                FROM docintel.documents d
                JOIN docintel.tenant_settings ts
                  ON ts.tenant_id = d.tenant_id AND ts.status = 'ACTIVE'
                WHERE d.upload_status = 'FIT'
                  -- RETRY_PENDING too (2026-10-01): a document whose fast second
                  -- attempt never ran otherwise waits on the legacy EOD scheduler alone.
                  AND d.processing_status IN ('FAILED', 'RETRY_PENDING')
                  -- only technical failures: a re-run cannot change a business
                  -- outcome or a configuration gap
                  AND (d.processing_failure_code IS NULL
                       OR NOT (d.processing_failure_code = ANY(:non_reprocessable_codes)))
                  -- one attempt at a time: a document whose earlier attempt
                  -- is still pending or running gets no second job alongside
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.processing_jobs active
                      WHERE active.tenant_id = d.tenant_id
                        AND active.document_id = d.document_id
                        AND active.job_status IN ('PENDING', 'RUNNING')
                  )
                  -- one nightly attempt per night, however quickly it failed
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.processing_jobs tonight
                      WHERE tonight.tenant_id = d.tenant_id
                        AND tonight.document_id = d.document_id
                        AND tonight.job_type = 'NIGHTLY_REPROCESS'
                        AND tonight.created_at_utc > :recent_cutoff
                  )
            """),
            {
                "first_attempt_no": _NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO,
                "non_reprocessable_codes": sorted(NIGHTLY_NON_REPROCESSABLE_CODES),
                "recent_cutoff": now - NIGHTLY_REPROCESS_MIN_INTERVAL,
            },
        )
    ).mappings().all()

    queued = 0
    for row in eligible_rows:
        next_attempt_no = int(row["last_attempt_no"]) + 1
        if next_attempt_no > _NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO + NIGHTLY_REPROCESS_MAX_ATTEMPTS - 1:
            continue
        # Keep the original request's correlation id so the attempt links back
        # to Audit Core's upload; generate one only when none was recorded.
        correlation_id = row["original_correlation_id"] or f"nightly.{uuid.uuid4()}"
        try:
            await session.execute(
                text("""
                    INSERT INTO docintel.processing_jobs
                        (tenant_id, processing_job_id, document_id, correlation_id,
                         job_type, job_status, due_at_utc, attempt_no, created_at_utc)
                    VALUES
                        (:tenant_id, :job_id, :doc_id, :corr,
                         'NIGHTLY_REPROCESS', 'PENDING', :now, :attempt_no, :now)
                    ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
                """),
                {
                    "tenant_id": row["tenant_id"],
                    "job_id": uuid.uuid4(),
                    "doc_id": row["document_id"],
                    "corr": correlation_id,
                    "now": now,
                    "attempt_no": next_attempt_no,
                },
            )
            queued += 1
        except Exception as exc:
            # Matches _insert_eod_retry_jobs' own established handling of
            # this same shape of loop -- log and move on rather than let one
            # bad row abort the whole nightly pass.
            logger.warning(
                "nightly_reprocess_job_insert_failed",
                tenant_id=row["tenant_id"],
                document_id=str(row["document_id"]),
                correlation_id=correlation_id,
                attempt_no=next_attempt_no,
                **safe_exception_context(exc),
            )

    return queued


async def insert_nightly_initial_jobs_for_unqueued(session: AsyncSession) -> int:
    """Every classified Capture V2 document that never got a reading job at
    all gets its INITIAL job tonight (decision 2026-10-01: after the night,
    no classified page stays unread). Until 2026-10-01 the classifier queued
    reading only for a page with an open checklist slot, so such documents
    exist; the classifier no longer skips them, and this is the backstop.
    Returns the number of jobs inserted."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            text("""
                SELECT d.tenant_id, d.document_id, d.correlation_id,
                       u.classified_document_type_key
                FROM docintel.documents d
                JOIN docintel.tenant_settings ts
                  ON ts.tenant_id = d.tenant_id AND ts.status = 'ACTIVE'
                JOIN docintel.document_capture_v2_uploads u
                  ON u.tenant_id = d.tenant_id AND u.document_id = d.document_id
                WHERE d.upload_status = 'FIT'
                  AND d.processing_status = 'NOT_STARTED'
                  AND u.state = 'CLASSIFIED'
                  AND u.classified_document_type_key IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.processing_jobs pj
                      WHERE pj.tenant_id = d.tenant_id AND pj.document_id = d.document_id
                  )
                ORDER BY d.registered_at_utc
            """),
        )
    ).mappings().all()
    queued = 0
    for row in rows:
        try:
            await session.execute(
                text("""
                    INSERT INTO docintel.processing_jobs
                        (tenant_id, processing_job_id, document_id, correlation_id,
                         job_type, job_status, due_at_utc, attempt_no, created_at_utc)
                    VALUES
                        (:tenant_id, :job_id, :doc_id, :corr, 'INITIAL', 'PENDING', :now, 1, :now)
                    ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
                """),
                {
                    "tenant_id": row["tenant_id"],
                    "job_id": uuid.uuid4(),
                    "doc_id": row["document_id"],
                    "corr": row["correlation_id"] or f"nightly.{uuid.uuid4()}",
                    "now": now,
                },
            )
            queued += 1
            logger.info(
                "nightly_unqueued_document_queued",
                tenant_id=row["tenant_id"],
                document_id=str(row["document_id"]),
                document_type_key=row["classified_document_type_key"],
            )
        except Exception as exc:
            logger.warning(
                "nightly_unqueued_job_insert_failed",
                tenant_id=row["tenant_id"],
                document_id=str(row["document_id"]),
                **safe_exception_context(exc),
            )
    return queued


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
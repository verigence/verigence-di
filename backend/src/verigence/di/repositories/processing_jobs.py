"""repositories/processing_jobs.py — Processing job repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_MAX_ERROR_DETAIL = 2000
_MAX_ERROR_CODE = 128

# The bounded V2 worker pool exists specifically to give Capture V2
# extraction a fast, PC-facing turnaround (see module docstring in
# workers/processor.py). Its first retryable failure must not fall back to
# the legacy EOD Retry Scheduler, which can leave a document showing
# nothing more than "still processing" for up to ~24h (see
# schedule_v2_fast_retry below).
V2_FAST_RETRY_DELAY_SECONDS = 120


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


NIGHTLY_REPROCESS_MAX_ATTEMPTS = 3
_NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO = 3  # 1=INITIAL, 2=EOD_RETRY/V2_FAST_RETRY, 3.. = nightly


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
                           gen_random_uuid()::text
                       ) AS original_correlation_id
                FROM docintel.documents d
                JOIN docintel.tenant_settings ts
                  ON ts.tenant_id = d.tenant_id AND ts.status = 'ACTIVE'
                WHERE d.upload_status = 'FIT'
                  AND d.processing_status = 'FAILED'
            """),
            {"first_attempt_no": _NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO},
        )
    ).mappings().all()

    queued = 0
    for row in eligible_rows:
        next_attempt_no = int(row["last_attempt_no"]) + 1
        if next_attempt_no > _NIGHTLY_REPROCESS_FIRST_ATTEMPT_NO + NIGHTLY_REPROCESS_MAX_ATTEMPTS - 1:
            continue
        correlation_id = f"nightly.{uuid.uuid4()}"
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
                error=str(exc),
            )

    return queued


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
        """),
        {
            "now": now,
            "error_code": safe_code,
            "error_detail": safe_detail,
            "tenant_id": tenant_id,
            "doc_id": document_id,
        },
    )
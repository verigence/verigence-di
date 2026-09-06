"""repositories/processing_jobs.py — Processing job repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_ERROR_DETAIL = 2000
_MAX_ERROR_CODE = 128


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
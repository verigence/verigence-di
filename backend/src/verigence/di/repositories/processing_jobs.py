"""repositories/processing_jobs.py — Processing job repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


async def claim_next_job(
    session: AsyncSession,
    *,
    worker_id: str,
) -> dict | None:  # type: ignore[type-arg]
    """Claim the next PENDING due job using FOR UPDATE SKIP LOCKED.

    Returns the claimed job dict or None if no jobs are available.
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            text("""
                SELECT tenant_id, processing_job_id, document_id, correlation_id,
                       job_type, attempt_no
                FROM docintel.processing_jobs
                WHERE job_status = 'PENDING'
                  AND due_at_utc <= :now
                ORDER BY due_at_utc
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
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
    }


async def complete_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    processing_job_id: uuid.UUID,
    success: bool,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a processing job COMPLETED or FAILED."""
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
            "error_code": error_code,
            "error_detail": error_detail,
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
            "error_code": error_code,
            "error_detail": error_detail,
            "tenant_id": tenant_id,
            "job_id": processing_job_id,
        },
    )
    await session.execute(
        text("""
            UPDATE docintel.documents d
            SET processing_status = 'RETRY_PENDING',
                confirmation_status = 'NOT_CONFIRMED',
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
            "error_code": error_code,
            "error_detail": error_detail,
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
            "error_code": error_code,
            "error_detail": error_detail,
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
            "error_code": error_code,
            "error_detail": error_detail,
            "tenant_id": tenant_id,
            "doc_id": document_id,
        },
    )

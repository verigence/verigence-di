"""repositories/documents.py — Document repository (async SQLAlchemy)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import (
    ConfirmationStatus,
    ContentState,
    ProcessingStatus,
    RetentionDisposition,
    SourceChannel,
    UploadStatus,
    VerificationState,
)


def _row_to_dict(row) -> dict:  # type: ignore[type-arg]
    """Convert a SQLAlchemy mapping row to a plain dict."""
    return {
        "tenant_id": row["tenant_id"],
        "document_id": row["document_id"],
        "subject_id": row["subject_id"],
        "source_channel": SourceChannel(row["source_channel"]),
        "upload_status": UploadStatus(row["upload_status"]),
        "processing_status": ProcessingStatus(row["processing_status"]),
        "confirmation_status": ConfirmationStatus(row["confirmation_status"]),
        "confidence_score": row["confidence_score"],
        "verification_threshold_applied": row["verification_threshold_applied"],
        "human_verification_status": row["human_verification_status"],
        "verification_state": VerificationState(row["verification_state"]),
        "content_state": ContentState(row["content_state"]),
        "original_filename": row["original_filename"],
        "declared_mime_type": row["declared_mime_type"],
        "detected_mime_type": row["detected_mime_type"],
        "file_size_bytes": row["file_size_bytes"],
        "content_hash_sha256": row["content_hash_sha256"],
        "page_count": row["page_count"],
        "correlation_id": row["correlation_id"],
        "registered_at_utc": row["registered_at_utc"],
        "processed_at_utc": row["processed_at_utc"],
        "confirmed_at_utc": row["confirmed_at_utc"],
        "upload_issue_code": row["upload_issue_code"],
        "upload_issue_detail": row["upload_issue_detail"],
        "processing_failure_code": row["processing_failure_code"],
        "duplicate_of_document_id": row["duplicate_of_document_id"],
        "replaces_document_id": row["replaces_document_id"],
    }


async def create_document_receiving(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
    source_channel: SourceChannel,
    uploaded_by_actor_id: str,
    uploaded_by_actor_type: str,
    correlation_id: str,
    retention_policy_id: uuid.UUID,
    retention_days: int,
    retention_disposition: RetentionDisposition,
    original_filename: str | None = None,
    declared_mime_type: str | None = None,
    source_device_id: str | None = None,
    captured_at: datetime | None = None,
    replaces_document_id: uuid.UUID | None = None,
) -> dict:  # type: ignore[type-arg]
    """Insert a RECEIVING Document row and return its data dict."""
    from datetime import timedelta

    now = datetime.now(UTC)
    document_id = uuid.uuid4()

    retention_until = (
        now + timedelta(days=retention_days) if retention_days > 0 else None
    )

    await session.execute(
        text("""
            INSERT INTO docintel.documents (
                tenant_id, document_id, subject_id,
                active_retention_policy_id, retention_until_utc, retention_disposition,
                source_channel, uploaded_by_actor_id, uploaded_by_actor_type,
                source_device_id, captured_at,
                registered_at_utc, correlation_id,
                original_filename, declared_mime_type,
                upload_status, processing_status, confirmation_status,
                verification_state, content_state,
                replaces_document_id,
                created_at_utc, updated_at_utc
            ) VALUES (
                :tenant_id, :document_id, :subject_id,
                :retention_policy_id, :retention_until, :retention_disposition,
                :source_channel, :actor_id, :actor_type,
                :device_id, :captured_at,
                :now, :correlation_id,
                :original_filename, :declared_mime_type,
                'RECEIVING', 'NOT_STARTED', 'PENDING',
                'NOT_VERIFIED', 'AVAILABLE',
                :replaces_document_id,
                :now, :now
            )
        """),
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "subject_id": subject_id,
            "retention_policy_id": retention_policy_id,
            "retention_until": retention_until,
            "retention_disposition": retention_disposition.value,
            "source_channel": source_channel.value,
            "actor_id": uploaded_by_actor_id,
            "actor_type": uploaded_by_actor_type,
            "device_id": source_device_id,
            "captured_at": captured_at,
            "now": now,
            "correlation_id": correlation_id,
            "original_filename": original_filename,
            "declared_mime_type": declared_mime_type,
            "replaces_document_id": replaces_document_id,
        },
    )
    # No commit here — caller manages transaction
    return {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "subject_id": subject_id,
        "source_channel": source_channel,
        "upload_status": UploadStatus.RECEIVING,
        "processing_status": ProcessingStatus.NOT_STARTED,
        "confirmation_status": ConfirmationStatus.PENDING,
        "confidence_score": None,
        "verification_threshold_applied": None,
        "human_verification_status": None,
        "verification_state": VerificationState.NOT_VERIFIED,
        "content_state": ContentState.AVAILABLE,
        "original_filename": original_filename,
        "declared_mime_type": declared_mime_type,
        "detected_mime_type": None,
        "file_size_bytes": None,
        "content_hash_sha256": None,
        "page_count": None,
        "correlation_id": correlation_id,
        "registered_at_utc": now,
        "processed_at_utc": None,
        "confirmed_at_utc": None,
        "upload_issue_code": None,
        "upload_issue_detail": None,
        "processing_failure_code": None,
        "duplicate_of_document_id": None,
        "replaces_document_id": replaces_document_id,
    }


async def update_document_upload_complete(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    file_size_bytes: int,
    content_hash_sha256: str,
    detected_mime_type: str,
    upload_status: UploadStatus,
    upload_issue_code: str | None = None,
    upload_issue_detail: str | None = None,
) -> None:
    """Update document after upload streaming is complete."""
    now = datetime.now(UTC)
    await session.execute(
        text("""
            UPDATE docintel.documents
            SET file_size_bytes = :bytes,
                content_hash_sha256 = :hash,
                detected_mime_type = :mime,
                upload_status = :status,
                upload_issue_code = :issue_code,
                upload_issue_detail = :issue_detail,
                updated_at_utc = :now
            WHERE tenant_id = :tenant_id AND document_id = :document_id
        """),
        {
            "bytes": file_size_bytes,
            "hash": content_hash_sha256,
            "mime": detected_mime_type,
            "status": upload_status.value,
            "issue_code": upload_issue_code,
            "issue_detail": upload_issue_detail,
            "now": now,
            "tenant_id": tenant_id,
            "document_id": document_id,
        },
    )


async def get_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    subject_id: uuid.UUID | None = None,
) -> dict | None:  # type: ignore[type-arg]
    """Fetch a single Document.  Optionally scope to subject_id."""
    conditions = "tenant_id = :tenant_id AND document_id = :document_id"
    params: dict = {"tenant_id": tenant_id, "document_id": document_id}  # type: ignore[type-arg]
    if subject_id is not None:
        conditions += " AND subject_id = :subject_id"
        params["subject_id"] = subject_id

    row = (
        await session.execute(
            text(f"""
                SELECT tenant_id, document_id, subject_id,
                       source_channel, upload_status, processing_status,
                       confirmation_status, confidence_score,
                       verification_threshold_applied, human_verification_status,
                       verification_state, content_state,
                       original_filename, declared_mime_type, detected_mime_type,
                       file_size_bytes, content_hash_sha256, page_count,
                       correlation_id, registered_at_utc, processed_at_utc, confirmed_at_utc,
                       upload_issue_code, upload_issue_detail, processing_failure_code,
                       duplicate_of_document_id, replaces_document_id
                FROM docintel.documents
                WHERE {conditions}
            """),
            params,
        )
    ).mappings().one_or_none()

    return _row_to_dict(row) if row is not None else None


async def list_subject_documents(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
) -> list[dict]:  # type: ignore[type-arg]
    """List all documents for a subject."""
    rows = (
        await session.execute(
            text("""
                SELECT tenant_id, document_id, subject_id,
                       source_channel, upload_status, processing_status,
                       confirmation_status, confidence_score,
                       verification_threshold_applied, human_verification_status,
                       verification_state, content_state,
                       original_filename, declared_mime_type, detected_mime_type,
                       file_size_bytes, content_hash_sha256, page_count,
                       correlation_id, registered_at_utc, processed_at_utc, confirmed_at_utc,
                       upload_issue_code, upload_issue_detail, processing_failure_code,
                       duplicate_of_document_id, replaces_document_id
                FROM docintel.documents
                WHERE tenant_id = :tenant_id AND subject_id = :subject_id
                ORDER BY registered_at_utc DESC
            """),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
    ).mappings().all()
    return [_row_to_dict(r) for r in rows]


async def get_active_retention_policy(
    session: AsyncSession,
    *,
    tenant_id: str,
) -> dict | None:  # type: ignore[type-arg]
    """Return the active retention policy for a tenant, or None."""
    row = (
        await session.execute(
            text("""
                SELECT rp.retention_policy_id, rp.retention_days, rp.disposition
                FROM docintel.retention_policies rp
                JOIN docintel.tenant_settings ts
                  ON ts.tenant_id = rp.tenant_id
                 AND ts.active_retention_policy_id = rp.retention_policy_id
                WHERE rp.tenant_id = :tenant_id
                  AND rp.status = 'ACTIVE'
            """),
            {"tenant_id": tenant_id},
        )
    ).mappings().one_or_none()

    if row is None:
        return None
    return {
        "retention_policy_id": row["retention_policy_id"],
        "retention_days": row["retention_days"],
        "disposition": RetentionDisposition(row["disposition"]),
    }

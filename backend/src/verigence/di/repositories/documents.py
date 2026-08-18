"""repositories/documents.py — Document repository (async SQLAlchemy)."""
from __future__ import annotations

import contextlib
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import (
    ConfirmationStatus,
    ContentState,
    ProcessingStatus,
    RetentionDisposition,
    UploadStatus,
    VerificationState,
)
from verigence.di.storage.adapter import StorageAdapter


def _row_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a SQLAlchemy mapping row to a plain dict.

    D11: only fields needed for the public API response are included.
    Internal fields (sourceChannel, hashes, MIME etc.) remain in DB but
    are not surfaced through the public document endpoints.
    """
    return {
        "tenant_id": row["tenant_id"],
        "document_id": row["document_id"],
        "subject_id": row["subject_id"],
        "document_type_key": row.get("document_type_key"),  # from LEFT JOIN on document_types
        "upload_status": UploadStatus(row["upload_status"]),
        "processing_status": ProcessingStatus(row["processing_status"]),
        "confirmation_status": ConfirmationStatus(row["confirmation_status"]),
        "confidence_score": row["confidence_score"],
        "verification_state": VerificationState(row["verification_state"]),
        "content_state": ContentState(row["content_state"]),
        "registered_at_utc": row["registered_at_utc"],
        # Keep internal fields for delete eligibility checks and worker access
        "upload_issue_code": row.get("upload_issue_code"),
        "upload_issue_detail": row.get("upload_issue_detail"),
        "processing_failure_code": row.get("processing_failure_code"),
    }


async def create_document_receiving(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
    source_channel: str | None = None,   # D10: nullable — caller no longer required
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
    document_type_hint_key: str | None = None,
    physical_form_type: str = "ADDITIONAL",
    requires_processing: bool = False,
    document_type_id: uuid.UUID | None = None,
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
                document_type_id,
                document_type_hint_key,
                physical_form_type,
                requires_processing,
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
                :document_type_id,
                :hint_key,
                :physical_form_type,
                :requires_processing,
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
            "document_type_id": document_type_id,
            "hint_key": document_type_hint_key,
            "physical_form_type": physical_form_type,
            "requires_processing": requires_processing,
            "retention_policy_id": retention_policy_id,
            "retention_until": retention_until,
            "retention_disposition": retention_disposition.value,
            "source_channel": source_channel,
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
        "document_type_key": None,  # resolved after processing; None at upload time
        "upload_status": UploadStatus.RECEIVING,
        "processing_status": ProcessingStatus.NOT_STARTED,
        "confirmation_status": ConfirmationStatus.PENDING,
        "confidence_score": None,
        "verification_state": VerificationState.NOT_VERIFIED,
        "content_state": ContentState.AVAILABLE,
        "registered_at_utc": now,
        "upload_issue_code": None,
        "upload_issue_detail": None,
        "processing_failure_code": None,
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
    """Fetch a single Document. Optionally scope to subject_id.

    Joins document_types to return document_type_key (D11).
    """
    conditions = "d.tenant_id = :tenant_id AND d.document_id = :document_id"
    params: dict = {"tenant_id": tenant_id, "document_id": document_id}  # type: ignore[type-arg]
    if subject_id is not None:
        conditions += " AND d.subject_id = :subject_id"
        params["subject_id"] = subject_id

    row = (
        await session.execute(
            text(f"""
                SELECT d.tenant_id, d.document_id, d.subject_id,
                       dt.document_type_key,
                       d.upload_status, d.processing_status,
                       d.confirmation_status, d.confidence_score,
                       d.verification_state, d.content_state,
                       d.registered_at_utc,
                       d.upload_issue_code, d.upload_issue_detail,
                       d.processing_failure_code
                FROM docintel.documents d
                LEFT JOIN docintel.document_types dt
                  ON dt.document_type_id = d.document_type_id
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
    """List all documents for a subject (D11)."""
    rows = (
        await session.execute(
            text("""
                SELECT d.tenant_id, d.document_id, d.subject_id,
                       dt.document_type_key,
                       d.upload_status, d.processing_status,
                       d.confirmation_status, d.confidence_score,
                       d.verification_state, d.content_state,
                       d.registered_at_utc,
                       d.upload_issue_code, d.upload_issue_detail,
                       d.processing_failure_code
                FROM docintel.documents d
                LEFT JOIN docintel.document_types dt
                  ON dt.document_type_id = d.document_type_id
                WHERE d.tenant_id = :tenant_id AND d.subject_id = :subject_id
                ORDER BY d.registered_at_utc DESC
            """),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
    ).mappings().all()
    return [_row_to_dict(r) for r in rows]


async def list_document_type_counts(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
) -> list[dict]:  # type: ignore[type-arg]
    """Count FIT documents per documentTypeKey for a subject (D12).

    Excludes REJECTED (NOT_FIT, CORRUPT, UPLOAD_FAILED) and documents
    without a resolved document_type_id (uploaded as ADDITIONAL/unknown).
    """
    rows = (
        await session.execute(
            text("""
                SELECT dt.document_type_key, COUNT(*) AS count
                FROM docintel.documents d
                JOIN docintel.document_types dt
                  ON dt.document_type_id = d.document_type_id
                WHERE d.tenant_id = :tenant_id
                  AND d.subject_id = :subject_id
                  AND d.upload_status = 'FIT'
                GROUP BY dt.document_type_key
                ORDER BY dt.document_type_key
            """),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
    ).mappings().all()
    return [{"documentTypeKey": r["document_type_key"], "count": r["count"]} for r in rows]


async def get_verification_threshold(
    session: AsyncSession,
    *,
    tenant_id: str,
) -> Decimal | None:
    """Return the tenant-specific verification threshold, or None if not set."""
    row = (
        await session.execute(
            text("""
                SELECT verification_threshold
                FROM docintel.tenant_settings
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id},
        )
    ).one_or_none()
    if row is None or row[0] is None:
        return None
    return Decimal(str(row[0]))


async def delete_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: uuid.UUID,
    subject_id: uuid.UUID,
    storage: StorageAdapter,
) -> None:
    """Hard-delete a document and all child rows except audit_events.

    Eligibility must be checked by the caller before invoking this function.
    Deletes in dependency order:
      document_field_values → validation_results → extracted_facts →
      processor_invocations → processing_runs → processing_jobs →
      document_quality_results → document_artifacts (+ object storage bytes) →
      documents
    audit_events are intentionally preserved.
    """

    # Load artifact keys before deleting rows
    artifact_rows = (
        await session.execute(
            text("""
                SELECT logical_object_key
                FROM docintel.document_artifacts
                WHERE tenant_id = :tid AND document_id = :doc_id
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).all()
    logical_keys = [r[0] for r in artifact_rows]

    # Delete child rows in dependency order
    for stmt in [
        "DELETE FROM docintel.document_field_values  WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.validation_results     WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.extracted_facts        WHERE tenant_id=:tid AND document_id=:doc_id",
        """DELETE FROM docintel.processor_invocations
               WHERE tenant_id=:tid
                 AND processing_run_id IN (
                     SELECT processing_run_id FROM docintel.processing_runs
                     WHERE tenant_id=:tid AND document_id=:doc_id
                 )""",
        "DELETE FROM docintel.processing_runs        WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.processing_jobs        WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.document_quality_results WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.document_artifacts     WHERE tenant_id=:tid AND document_id=:doc_id",
        "DELETE FROM docintel.documents              WHERE tenant_id=:tid AND document_id=:doc_id AND subject_id=:sid",
    ]:
        await session.execute(text(stmt), {"tid": tenant_id, "doc_id": document_id, "sid": subject_id})

    # Delete object storage bytes for each artifact
    for key in logical_keys:
        with contextlib.suppress(Exception):
            await storage.delete(key)


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

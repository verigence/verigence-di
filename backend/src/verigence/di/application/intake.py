"""application/intake.py — Document Intake use case.

Generic DI intake keeps the D5 Subject-centric path. UC02 Audit Core-originated
intake can additionally supply one immutable D28 Audit storage context; DI then
links the Document to that context and constructs the business-hierarchy key.
"""
from __future__ import annotations

import hashlib
import io
import time
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import UploadStatus
from verigence.di.quality.validator import validate_upload
from verigence.di.repositories.documents import (
    create_document_receiving,
    get_active_retention_policy,
    update_document_upload_complete,
)
from verigence.di.repositories.processing_jobs import create_initial_job
from verigence.di.storage.adapter import StorageAdapter, build_original_key
from verigence.di.storage.audit_keys import build_audit_original_key

logger = structlog.get_logger(__name__)

_DEFAULT_ALLOWED_MIME: frozenset[str] = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/tiff", "image/gif", "image/bmp",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "text/plain", "text/csv", "application/zip",
})
_MAX_BYTES_DEFAULT = 30 * 1024 * 1024


async def _stream_and_hash(upload: UploadFile, max_bytes: int) -> tuple[bytes, int, str]:
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Upload exceeds maximum size of {max_bytes} bytes")
        hasher.update(chunk)
        chunks.append(chunk)
    return b"".join(chunks), total, hasher.hexdigest()


async def intake_document(
    *,
    session: AsyncSession,
    storage: StorageAdapter,
    tenant_id: str,
    subject_id: uuid.UUID,
    uploaded_by_actor_id: str,
    uploaded_by_actor_type: str,
    correlation_id: str,
    upload: UploadFile,
    document_type_key: str | None = None,
    audit_storage_context: dict[str, object] | None = None,
) -> dict:  # type: ignore[type-arg]
    """Execute document intake, optionally under a frozen Audit business context."""
    intake_start = time.monotonic()
    log = logger.bind(
        tenant_id=tenant_id,
        subject_id=str(subject_id),
        actor_id=uploaded_by_actor_id,
        actor_type=uploaded_by_actor_type,
        correlation_id=correlation_id,
        document_type_key=document_type_key or "unknown",
    )
    log.info("upload_received", filename=upload.filename, declared_mime=upload.content_type)

    retention = await get_active_retention_policy(session, tenant_id=tenant_id)
    if retention is None:
        raise ValueError("Tenant has no active retention policy configured")

    physical_form_type = "ADDITIONAL"
    requires_processing = False
    resolved_document_type_id = None
    if document_type_key:
        tdt_row = (
            await session.execute(
                text("""
                    SELECT tdt.physical_form_type, tdt.requires_processing,
                           dt.document_type_id
                    FROM docintel.tenant_document_types tdt
                    JOIN docintel.document_types dt
                      ON dt.document_type_id = tdt.document_type_id
                    WHERE tdt.tenant_id = :tid
                      AND dt.document_type_key = :key
                      AND tdt.is_active = true
                    LIMIT 1
                """),
                {"tid": tenant_id, "key": document_type_key},
            )
        ).one_or_none()
        if tdt_row:
            physical_form_type = tdt_row[0]
            requires_processing = tdt_row[1]
            resolved_document_type_id = tdt_row[2]
            log.info(
                "type_resolved",
                document_type_key=document_type_key,
                physical_form_type=physical_form_type,
                requires_processing=requires_processing,
            )
        else:
            log.info(
                "type_resolved",
                document_type_key=document_type_key,
                physical_form_type="ADDITIONAL",
                requires_processing=False,
                note="unrecognised_type_key",
            )

    subject_row = (
        await session.execute(
            text("""
                SELECT display_name FROM docintel.subjects
                WHERE tenant_id = :tid AND subject_id = :sid
            """),
            {"tid": tenant_id, "sid": subject_id},
        )
    ).one_or_none()
    if subject_row is None:
        raise ValueError("Subject does not exist in target Tenant")
    subject_display_name: str | None = subject_row[0]

    if audit_storage_context is not None:
        if audit_storage_context.get("tenant_id") != tenant_id:
            raise ValueError("Audit storage context Tenant does not match intake Tenant")
        if audit_storage_context.get("subject_id") != subject_id:
            raise ValueError("Audit storage context Subject does not match intake Subject")

    doc = await create_document_receiving(
        session,
        tenant_id=tenant_id,
        subject_id=subject_id,
        source_channel=None,
        uploaded_by_actor_id=uploaded_by_actor_id,
        uploaded_by_actor_type=uploaded_by_actor_type,
        correlation_id=correlation_id,
        retention_policy_id=retention["retention_policy_id"],
        retention_days=retention["retention_days"],
        retention_disposition=retention["disposition"],
        original_filename=upload.filename,
        declared_mime_type=upload.content_type,
        document_type_hint_key=document_type_key,
        physical_form_type=physical_form_type,
        requires_processing=requires_processing,
        document_type_id=resolved_document_type_id,
    )
    document_id: uuid.UUID = doc["document_id"]

    storage_context_id: uuid.UUID | None = None
    if audit_storage_context is not None:
        storage_context_id = _context_uuid(audit_storage_context, "storage_context_id")
        await session.execute(
            text("""
                UPDATE docintel.documents
                SET audit_storage_context_id = :storage_context_id,
                    updated_at_utc = now()
                WHERE tenant_id = :tenant_id AND document_id = :document_id
            """),
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "storage_context_id": storage_context_id,
            },
        )
        logical_key = build_audit_original_key(
            tenant_id=tenant_id,
            dealer_id=_context_uuid(audit_storage_context, "dealer_id"),
            dealer_outlet_id=_context_uuid(audit_storage_context, "dealer_outlet_id"),
            customer_id=_context_uuid(audit_storage_context, "customer_id"),
            project_slug=_context_string(audit_storage_context, "project_slug"),
            dealer_slug=_context_string(audit_storage_context, "dealer_slug"),
            dealer_outlet_slug=_context_string(audit_storage_context, "dealer_outlet_slug"),
            customer_slug=_context_string(audit_storage_context, "customer_slug"),
            document_id=document_id,
            physical_form_type=physical_form_type,
            original_filename=upload.filename,
            detected_mime_type=upload.content_type,
        )
    else:
        logical_key = build_original_key(
            tenant_id=tenant_id,
            subject_id=subject_id,
            subject_display_name=subject_display_name,
            document_id=document_id,
            physical_form_type=physical_form_type,
            original_filename=upload.filename,
            detected_mime_type=upload.content_type,
        )

    artifact_id = uuid.uuid4()
    try:
        raw_bytes, byte_count, sha256_hex = await _stream_and_hash(upload, _MAX_BYTES_DEFAULT)
    except ValueError as exc:
        await update_document_upload_complete(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            file_size_bytes=0,
            content_hash_sha256="",
            detected_mime_type=upload.content_type or "",
            upload_status=UploadStatus.UPLOAD_FAILED,
            upload_issue_code="FILE_TOO_LARGE",
            upload_issue_detail=str(exc),
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.UPLOAD_FAILED
        doc["upload_issue_code"] = "FILE_TOO_LARGE"
        return doc

    detected_mime = _detect_mime(raw_bytes, upload.filename or "")
    log.info(
        "mime_detected",
        declared_mime=upload.content_type,
        detected_mime=detected_mime,
        match=(detected_mime == upload.content_type),
        bytes=byte_count,
    )

    if detected_mime not in _DEFAULT_ALLOWED_MIME:
        await update_document_upload_complete(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            file_size_bytes=byte_count,
            content_hash_sha256=sha256_hex,
            detected_mime_type=detected_mime,
            upload_status=UploadStatus.CORRUPT,
            upload_issue_code="MIME_TYPE_NOT_ALLOWED",
            upload_issue_detail=f"Detected MIME type {detected_mime!r} is not allowed",
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.CORRUPT
        doc["upload_issue_code"] = "MIME_TYPE_NOT_ALLOWED"
        return doc

    try:
        storage_meta = await storage.put_stream(
            logical_key=logical_key,
            stream=io.BytesIO(raw_bytes),
            content_type=detected_mime,
            metadata={
                "document_id": str(document_id),
                "tenant_id": tenant_id,
                "sha256": sha256_hex,
            },
        )
        storage_id = storage_meta.storage_id
        log.info(
            "storage_written",
            document_id=str(document_id),
            logical_key=logical_key,
            bytes_written=byte_count,
            sha256=sha256_hex[:16] + "…",
        )
    except Exception as exc:
        log.error(
            "intake_error",
            step="storage_write",
            document_id=str(document_id),
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        await update_document_upload_complete(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            file_size_bytes=byte_count,
            content_hash_sha256=sha256_hex,
            detected_mime_type=detected_mime,
            upload_status=UploadStatus.UPLOAD_FAILED,
            upload_issue_code="STORAGE_ERROR",
            upload_issue_detail=str(exc),
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.UPLOAD_FAILED
        return doc

    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.document_artifacts
                (tenant_id, artifact_id, document_id, storage_id,
                 logical_object_key, artifact_type, mime_type,
                 file_size_bytes, content_hash_sha256, created_at_utc)
            VALUES
                (:tenant_id, :artifact_id, :document_id, :storage_id,
                 :logical_key, 'ORIGINAL', :mime,
                 :size, :sha256, :now)
        """),
        {
            "tenant_id": tenant_id,
            "artifact_id": artifact_id,
            "document_id": document_id,
            "storage_id": uuid.UUID(str(storage_id)) if not isinstance(storage_id, uuid.UUID) else storage_id,
            "logical_key": logical_key,
            "mime": detected_mime,
            "size": byte_count,
            "sha256": sha256_hex,
            "now": now,
        },
    )

    validator_result = await validate_upload(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        data=raw_bytes,
        declared_mime=upload.content_type,
        filename=upload.filename,
    )
    await update_document_upload_complete(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        file_size_bytes=byte_count,
        content_hash_sha256=sha256_hex,
        detected_mime_type=validator_result.detected_mime or detected_mime,
        upload_status=validator_result.upload_status,
        upload_issue_code=validator_result.upload_issue_code,
        upload_issue_detail=validator_result.upload_issue_detail,
    )

    if validator_result.upload_status == UploadStatus.FIT and requires_processing:
        job = await create_initial_job(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            correlation_id=correlation_id,
        )
        log.info(
            "processing_job_created",
            document_id=str(document_id),
            processing_job_id=str(job),
            job_type="INITIAL",
        )

    await session.commit()
    doc.update({
        "upload_status": validator_result.upload_status,
        "file_size_bytes": byte_count,
        "content_hash_sha256": sha256_hex,
        "detected_mime_type": validator_result.detected_mime or detected_mime,
        "upload_issue_code": validator_result.upload_issue_code,
        "upload_issue_detail": validator_result.upload_issue_detail,
        "audit_storage_context_id": storage_context_id,
    })

    duration_ms = round((time.monotonic() - intake_start) * 1000, 1)
    failed_rules = [
        result.rule_key
        for result in validator_result.quality_results
        if result.outcome == "FAIL"
    ]
    if validator_result.upload_status == UploadStatus.FIT:
        log.info(
            "quality_verdict",
            document_id=str(document_id),
            upload_status=validator_result.upload_status.value,
            rules_run=len(validator_result.quality_results),
            rules_failed=len(failed_rules),
            failed_rule_keys=failed_rules,
            total_duration_ms=duration_ms,
        )
    else:
        log.warning(
            "upload_rejected",
            document_id=str(document_id),
            upload_status=validator_result.upload_status.value,
            failed_rule_keys=failed_rules,
            total_duration_ms=duration_ms,
        )
    return doc


def _context_uuid(context: dict[str, object], key: str) -> uuid.UUID:
    value = context.get(key)
    if not isinstance(value, uuid.UUID):
        raise ValueError(f"Audit storage context {key} is invalid")
    return value


def _context_string(context: dict[str, object], key: str) -> str:
    value = context.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Audit storage context {key} is invalid")
    return value


def _detect_mime(data: bytes, filename: str) -> str:
    try:
        import magic
        return magic.from_buffer(data[:2048], mime=True)
    except Exception:
        pass
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) > 8 and data[8:12] == b"WEBP":
        return "image/webp"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }.get(ext, "application/octet-stream")

"""application/intake.py — Document Intake use case.

Implements the LLD §Document Intake Service contract:
1.  Allocate document_id → RECEIVING row
2.  Allocate ORIGINAL artifact ID / logical key
3.  Stream bytes to StorageAdapter while computing SHA-256 + byte count
4.  Finalize storage metadata → artifact row
5.  Move Document → VALIDATING
6.  Integrity check (size limit, MIME detection)
7.  Persist to storage + artifact row
8.  Quality gate (validate_upload) — structural + tenant quality-policy rules
9.  Update Document to final upload status (FIT | NOT_FIT | CORRUPT)
10. For FIT: create INITIAL processing job + fire pg_notify to wake worker
11. Return Document data dict

The caller (router) is responsible for:
- Auth / RBAC
- Tenant + Subject path validation
- Idempotency header handling (Phase 2)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import (
    UploadStatus,
)
from verigence.di.quality.validator import validate_upload
from verigence.di.repositories.documents import (
    create_document_receiving,
    get_active_retention_policy,
    update_document_upload_complete,
)
from verigence.di.repositories.processing_jobs import create_initial_job
from verigence.di.storage.adapter import StorageAdapter, build_original_key

logger = structlog.get_logger(__name__)

# Allowed MIME types — kept in sync with _MIME_EXT in storage/adapter.py.
# Full list so Office docs, CSV, ZIP are accepted and not rejected as CORRUPT.
_DEFAULT_ALLOWED_MIME: frozenset[str] = frozenset({
    # Images
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
    "image/gif",
    "image/bmp",
    # PDF
    "application/pdf",
    # Microsoft Office (modern)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # Microsoft Office (legacy)
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    # OpenDocument
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    # Text / CSV
    "text/plain",
    "text/csv",
    # Archives
    "application/zip",
})
_MAX_BYTES_DEFAULT = 30 * 1024 * 1024  # 30 MB default, overridden by Tenant config


async def _stream_and_hash(
    upload: UploadFile,
    max_bytes: int,
) -> tuple[bytes, int, str]:
    """Stream the upload, compute SHA-256 and byte count.

    Returns (raw_bytes, byte_count, hex_sha256).
    Raises ValueError if the file exceeds max_bytes.
    """
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await upload.read(64 * 1024)  # 64 KB chunks
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
) -> dict:  # type: ignore[type-arg]
    """Execute the full document intake flow.

    Returns the final Document data dict (with upload_status populated).
    """
    import time as _time
    _intake_start = _time.monotonic()

    log = logger.bind(
        tenant_id=tenant_id,
        subject_id=str(subject_id),
        actor_id=uploaded_by_actor_id,
        actor_type=uploaded_by_actor_type,
        correlation_id=correlation_id,
        document_type_key=document_type_key or "unknown",
    )
    log.info(
        "upload_received",
        filename=upload.filename,
        declared_mime=upload.content_type,
    )

    # ── Step 1: Fetch tenant retention policy ────────────────────────────────
    retention = await get_active_retention_policy(session, tenant_id=tenant_id)
    if retention is None:
        raise ValueError("Tenant has no active retention policy configured")

    # ── Step 2: Resolve document type from tenant_document_types (D4) ────────
    # If documentTypeKey is absent or unrecognised → ADDITIONAL / no processing.
    from sqlalchemy import text
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

    # ── Step 3: Fetch subject display_name for path building (D5) ────────────
    subject_row = (
        await session.execute(
            text("""
                SELECT display_name FROM docintel.subjects
                WHERE tenant_id = :tid AND subject_id = :sid
            """),
            {"tid": tenant_id, "sid": subject_id},
        )
    ).one_or_none()
    subject_display_name: str | None = subject_row[0] if subject_row else None

    # ── Step 4: Create RECEIVING document row ────────────────────────────────
    doc = await create_document_receiving(
        session,
        tenant_id=tenant_id,
        subject_id=subject_id,
        source_channel=None,        # D10: no longer from caller
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

    # ── Step 5: Build R2 object key (D5) ─────────────────────────────────────
    artifact_id = uuid.uuid4()
    logical_key = build_original_key(
        tenant_id=tenant_id,
        subject_id=subject_id,
        subject_display_name=subject_display_name,
        document_id=document_id,
        physical_form_type=physical_form_type,
        original_filename=upload.filename,
        detected_mime_type=upload.content_type,
    )

    # ── Step 5: Stream bytes to storage ──────────────────────────────────────
    max_bytes = _MAX_BYTES_DEFAULT

    try:
        raw_bytes, byte_count, sha256_hex = await _stream_and_hash(upload, max_bytes)
    except ValueError as exc:
        # Exceeds size limit → UPLOAD_FAILED (canonical code: FILE_TOO_LARGE)
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

    # Detect MIME from bytes
    detected_mime = _detect_mime(raw_bytes, upload.filename or "")
    log.info(
        "mime_detected",
        declared_mime=upload.content_type,
        detected_mime=detected_mime,
        match=(detected_mime == upload.content_type),
        bytes=byte_count,
    )

    # ── Step 6: MIME/integrity check ─────────────────────────────────────────
    if detected_mime not in _DEFAULT_ALLOWED_MIME:
        await update_document_upload_complete(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            file_size_bytes=byte_count,
            content_hash_sha256=sha256_hex,
            detected_mime_type=detected_mime,
            upload_status=UploadStatus.CORRUPT,
            upload_issue_code="MIME_TYPE_NOT_ALLOWED",  # v2.2 canonical code
            upload_issue_detail=f"Detected MIME type {detected_mime!r} is not allowed",
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.CORRUPT
        doc["upload_issue_code"] = "MIME_TYPE_NOT_ALLOWED"
        return doc

    # ── Step 7: Persist to storage ────────────────────────────────────────────
    import io
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
        import time as _time2
        log.info(
            "storage_written",
            document_id=str(document_id),
            r2_key=logical_key,
            bytes_written=byte_count,
            sha256=sha256_hex[:16] + "…",
        )
    except Exception as exc:
        log.error(
            "intake_error",
            step="storage_write",
            document_id=str(document_id) if "document_id" in dir() else "unknown",
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

    # ── Step 8: Persist artifact row ─────────────────────────────────────────
    now = datetime.now(UTC)
    from sqlalchemy import text
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

    # ── Step 8: Quality gate ──────────────────────────────────────────────────
    validator_result = await validate_upload(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        data=raw_bytes,
        declared_mime=upload.content_type,
        filename=upload.filename,
    )

    # ── Step 9: Persist final upload status ───────────────────────────────────
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

    # ── Step 10: For FIT documents — create processing job + notify worker ────
    # requires_processing=False (ADDITIONAL) → skip Document AI entirely (D4)
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
        # Fire pg_notify within the same transaction so the worker wakes
        # immediately after commit instead of waiting for the next poll tick.
        # Auto-suppressed if this transaction rolls back — no spurious wakes.
        await session.execute(
            text("SELECT pg_notify('di_processing_jobs', :payload)"),
            {"payload": str(job)},
        )
        log.info(
            "notify_sent",
            document_id=str(document_id),
            processing_job_id=str(job),
        )

    await session.commit()

    # Update the return dict with final state
    doc.update({
        "upload_status": validator_result.upload_status,
        "file_size_bytes": byte_count,
        "content_hash_sha256": sha256_hex,
        "detected_mime_type": validator_result.detected_mime or detected_mime,
        "upload_issue_code": validator_result.upload_issue_code,
        "upload_issue_detail": validator_result.upload_issue_detail,
    })

    import time as _time3
    _duration_ms = round((_time3.monotonic() - _intake_start) * 1000, 1)
    failed_rules = [
        r.rule_key for r in (validator_result.quality_results or [])
        if not r.passed
    ] if hasattr(validator_result, "quality_results") else []

    if validator_result.upload_status == UploadStatus.FIT:
        log.info(
            "quality_verdict",
            document_id=str(document_id),
            upload_status=validator_result.upload_status.value,
            rules_run=len(validator_result.quality_results or []),
            rules_failed=len(failed_rules),
            failed_rule_keys=failed_rules,
            total_duration_ms=_duration_ms,
        )
    else:
        log.warning(
            "upload_rejected",
            document_id=str(document_id),
            upload_status=validator_result.upload_status.value,
            failed_rule_keys=failed_rules,
            total_duration_ms=_duration_ms,
        )
    return doc


def _detect_mime(data: bytes, filename: str) -> str:
    """Detect MIME type from file bytes using python-magic or fallback."""
    try:
        import magic  # type: ignore[import]
        return magic.from_buffer(data[:2048], mime=True)
    except Exception:
        pass

    # Fallback: simple header sniffing
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] in (b"\xff\xd8\xff",):
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] in (b"RIFF",) and len(data) > 8 and data[8:12] == b"WEBP":
        return "image/webp"
    # Last resort: use filename extension
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

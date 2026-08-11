"""application/intake.py — Document Intake use case.

Implements the LLD §Document Intake Service contract:
1.  Allocate document_id → RECEIVING row
2.  Allocate ORIGINAL artifact ID / logical key
3.  Stream bytes to StorageAdapter while computing SHA-256 + byte count
4.  Finalize storage metadata → artifact row
5.  Move Document → VALIDATING
6.  Integrity + quality gate (MIME check, size check)
7.  Update Document to final upload status
8.  For FIT evidence: create INITIAL processing job
9.  Return Document data dict

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
    SourceChannel,
    UploadStatus,
)
from verigence.di.repositories.documents import (
    create_document_receiving,
    get_active_retention_policy,
    update_document_upload_complete,
)
from verigence.di.repositories.processing_jobs import create_initial_job
from verigence.di.storage.adapter import StorageAdapter

logger = structlog.get_logger(__name__)

# Allowed MIME types for now — these will come from Tenant config in a full impl
_DEFAULT_ALLOWED_MIME: frozenset[str] = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/tiff",
    "application/pdf",
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
    source_channel: SourceChannel,
    uploaded_by_actor_id: str,
    uploaded_by_actor_type: str,
    correlation_id: str,
    upload: UploadFile,
    document_type_key: str | None = None,
    captured_at: datetime | None = None,
    source_reference: str | None = None,
    replaces_document_id: uuid.UUID | None = None,
    source_device_id: str | None = None,
) -> dict:  # type: ignore[type-arg]
    """Execute the full document intake flow.

    Returns the final Document data dict (with upload_status populated).
    """
    # ── Step 1: Fetch tenant retention policy ────────────────────────────────
    retention = await get_active_retention_policy(session, tenant_id=tenant_id)
    if retention is None:
        # No active retention policy → cannot accept production uploads
        raise ValueError("Tenant has no active retention policy configured")

    # ── Step 2: Create RECEIVING document row ────────────────────────────────
    doc = await create_document_receiving(
        session,
        tenant_id=tenant_id,
        subject_id=subject_id,
        source_channel=source_channel,
        uploaded_by_actor_id=uploaded_by_actor_id,
        uploaded_by_actor_type=uploaded_by_actor_type,
        correlation_id=correlation_id,
        retention_policy_id=retention["retention_policy_id"],
        retention_days=retention["retention_days"],
        retention_disposition=retention["disposition"],
        original_filename=upload.filename,
        declared_mime_type=upload.content_type,
        source_device_id=source_device_id,
        captured_at=captured_at,
        replaces_document_id=replaces_document_id,
    )
    document_id: uuid.UUID = doc["document_id"]

    # ── Step 3: Fetch tenant storage key ─────────────────────────────────────
    from sqlalchemy import text
    row = (
        await session.execute(
            text("SELECT tenant_storage_key FROM docintel.tenant_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).one_or_none()
    tenant_storage_key: str = str(row[0]) if row else str(uuid.uuid4())

    # ── Step 4: Allocate ORIGINAL artifact ───────────────────────────────────
    artifact_id = uuid.uuid4()
    logical_key = (
        f"tenants/{tenant_storage_key}/documents/{document_id}"
        f"/original/{artifact_id}"
    )

    # ── Step 5: Stream bytes to storage ──────────────────────────────────────
    max_bytes = _MAX_BYTES_DEFAULT

    try:
        raw_bytes, byte_count, sha256_hex = await _stream_and_hash(upload, max_bytes)
    except ValueError as exc:
        # Exceeds size limit → UPLOAD_FAILED
        await update_document_upload_complete(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            file_size_bytes=0,
            content_hash_sha256="",
            detected_mime_type=upload.content_type or "",
            upload_status=UploadStatus.UPLOAD_FAILED,
            upload_issue_code="SIZE_EXCEEDED",
            upload_issue_detail=str(exc),
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.UPLOAD_FAILED
        doc["upload_issue_code"] = "SIZE_EXCEEDED"
        return doc

    # Detect MIME from bytes
    detected_mime = _detect_mime(raw_bytes, upload.filename or "")

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
            upload_issue_code="UNSUPPORTED_MIME",
            upload_issue_detail=f"Detected MIME type {detected_mime!r} is not allowed",
        )
        await session.commit()
        doc["upload_status"] = UploadStatus.CORRUPT
        doc["upload_issue_code"] = "UNSUPPORTED_MIME"
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
    except Exception as exc:
        logger.error("storage_put_failed", error=str(exc), document_id=str(document_id))
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

    # ── Step 9: Mark FIT + create processing job ─────────────────────────────
    await update_document_upload_complete(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        file_size_bytes=byte_count,
        content_hash_sha256=sha256_hex,
        detected_mime_type=detected_mime,
        upload_status=UploadStatus.FIT,
    )

    await create_initial_job(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        correlation_id=correlation_id,
    )

    await session.commit()

    # Update the return dict
    doc.update({
        "upload_status": UploadStatus.FIT,
        "file_size_bytes": byte_count,
        "content_hash_sha256": sha256_hex,
        "detected_mime_type": detected_mime,
    })

    logger.info(
        "document_intake_complete",
        document_id=str(document_id),
        tenant_id=tenant_id,
        subject_id=str(subject_id),
        bytes=byte_count,
        upload_status="FIT",
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

"""api/v1/unassigned.py — Unassigned WhatsApp document routes.

OAS operations (6):
  GET /v1/tenants/{tenantId}/unassigned-documents
      → getUnassignedDocuments          (unassigned_document:read)
  GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}
      → getUnassignedDocument           (unassigned_document:read)
  GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/content
      → getUnassignedDocumentContent    (unassigned_document:read)
  GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/fields
      → getUnassignedDocumentFields     (unassigned_document:read)
  GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/quality
      → getUnassignedDocumentQuality    (unassigned_document:read)
  PUT /v1/tenants/{tenantId}/unassigned-documents/{documentId}/subject
      → assignDocumentSubject           (unassigned_document:assign)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session
from verigence.di.storage.adapter import get_storage_adapter

router = APIRouter(prefix="/v1", tags=["WhatsApp"])


# ── GET /v1/tenants/{tenantId}/unassigned-documents ───────────────────────────

@router.get("/tenants/{tenant_id}/unassigned-documents")
async def get_unassigned_documents(
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_READ)
    ),
) -> dict[str, Any]:
    offset = (max(1, page) - 1) * min(200, page_size)
    limit = min(200, page_size)
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT document_id, upload_status, processing_status,
                           confirmation_status, source_channel, registered_at_utc
                    FROM docintel.documents
                    WHERE tenant_id = :tid AND subject_id IS NULL
                    ORDER BY registered_at_utc DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"tid": tenant_id, "limit": limit, "offset": offset},
            )
        ).mappings().all()
        total = (
            await session.execute(
                text("""
                    SELECT COUNT(*) FROM docintel.documents
                    WHERE tenant_id = :tid AND subject_id IS NULL
                """),
                {"tid": tenant_id},
            )
        ).scalar()
    return {
        "items": [_fmt_doc(r) for r in rows],
        "page": page,
        "pageSize": page_size,
        "total": total or 0,
    }


# ── GET /v1/tenants/{tenantId}/unassigned-documents/{documentId} ──────────────

@router.get("/tenants/{tenant_id}/unassigned-documents/{document_id}")
async def get_unassigned_document(
    tenant_id: str,
    document_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = await _fetch_unassigned_doc(session, tenant_id, document_id)
    if not row:
        raise problem(404, "Unassigned document not found", ErrorCode.DOCUMENT_NOT_FOUND)
    return _fmt_doc(row)


# ── GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/content ──────

@router.get("/tenants/{tenant_id}/unassigned-documents/{document_id}/content")
async def get_unassigned_document_content(
    tenant_id: str,
    document_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_READ)
    ),
) -> Response:
    async with tenant_session(tenant_id) as session:
        art_row = (
            await session.execute(
                text("""
                    SELECT da.logical_object_key, da.mime_type, d.content_hash_sha256,
                           d.content_state
                    FROM docintel.document_artifacts da
                    JOIN docintel.documents d
                      ON d.tenant_id = da.tenant_id AND d.document_id = da.document_id
                    WHERE da.tenant_id = :tid AND da.document_id = :doc_id
                      AND da.artifact_type = 'ORIGINAL'
                      AND d.subject_id IS NULL
                    LIMIT 1
                """),
                {"tid": tenant_id, "doc_id": document_id},
            )
        ).one_or_none()

    if not art_row:
        raise problem(404, "Unassigned document not found", ErrorCode.DOCUMENT_NOT_FOUND)
    if art_row[3] == "PURGED":
        raise problem(410, "Document content has been purged", ErrorCode.DOCUMENT_CONTENT_PURGED)

    storage = get_storage_adapter()
    chunks = []
    async for chunk in await storage.get_stream(art_row[0]):
        chunks.append(chunk)
    data = b"".join(chunks)

    headers = {}
    if art_row[2]:
        headers["X-Content-SHA256"] = art_row[2]
    return Response(
        content=data,
        media_type=art_row[1] or "application/octet-stream",
        headers=headers,
    )


# ── GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/fields ───────

@router.get("/tenants/{tenant_id}/unassigned-documents/{document_id}/fields")
async def get_unassigned_document_fields(
    tenant_id: str,
    document_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_READ)
    ),
) -> dict[str, Any]:
    """Return extraction result for an unassigned document."""
    async with tenant_session(tenant_id) as session:
        doc_row = await _fetch_unassigned_doc(session, tenant_id, document_id)
        if not doc_row:
            raise problem(404, "Unassigned document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row["confirmation_status"] != "CONFIRMED":
            raise problem(409, "Document is not yet CONFIRMED — fields not available",
                          ErrorCode.INVALID_DOCUMENT_STATE)

        fields = await _fetch_field_values(session, tenant_id, document_id)
    return {
        "documentId": str(document_id),
        "fields": fields,
    }


# ── GET /v1/tenants/{tenantId}/unassigned-documents/{documentId}/quality ──────

@router.get("/tenants/{tenant_id}/unassigned-documents/{document_id}/quality")
async def get_unassigned_document_quality(
    tenant_id: str,
    document_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        doc_row = await _fetch_unassigned_doc(session, tenant_id, document_id)
        if not doc_row:
            raise problem(404, "Unassigned document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        rows = (
            await session.execute(
                text("""
                    SELECT rule_key, outcome, parameters_applied,
                           measurement, message, evaluated_at_utc
                    FROM docintel.document_quality_results
                    WHERE tenant_id = :tid AND document_id = :doc_id
                    ORDER BY evaluated_at_utc DESC
                """),
                {"tid": tenant_id, "doc_id": document_id},
            )
        ).mappings().all()
    return {
        "documentId": str(document_id),
        "qualityResults": [
            {
                "ruleKey": r["rule_key"],
                "outcome": r["outcome"],
                "parametersApplied": r["parameters_applied"],
                "measurement": r["measurement"],
                "message": r["message"],
                "evaluatedAt": r["evaluated_at_utc"].isoformat() if r.get("evaluated_at_utc") else None,
            }
            for r in rows
        ],
    }


# ── PUT /v1/tenants/{tenantId}/unassigned-documents/{documentId}/subject ──────

@router.put("/tenants/{tenant_id}/unassigned-documents/{document_id}/subject")
async def assign_document_subject(
    tenant_id: str,
    document_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.UNASSIGNED_DOCUMENT_ASSIGN)
    ),
) -> dict[str, Any]:
    """Assign an unassigned tenant document to a Subject."""
    subject_id_str: str | None = body.get("subjectId")
    if not subject_id_str:
        raise problem(422, "subjectId is required", ErrorCode.VALIDATION_ERROR)
    subject_id = uuid.UUID(subject_id_str)
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        doc_row = await _fetch_unassigned_doc(session, tenant_id, document_id)
        if not doc_row:
            raise problem(404, "Unassigned document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row.get("subject_id"):
            raise problem(409, "Document already has a Subject assigned",
                          ErrorCode.INVALID_DOCUMENT_STATE)

        subj_exists = (
            await session.execute(
                text("""
                    SELECT 1 FROM docintel.subjects
                    WHERE tenant_id = :tid AND subject_id = :sid AND status = 'ACTIVE'
                """),
                {"tid": tenant_id, "sid": subject_id},
            )
        ).one_or_none()
        if not subj_exists:
            raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)

        await session.execute(
            text("""
                UPDATE docintel.documents
                SET subject_id = :sid, updated_at_utc = :now
                WHERE tenant_id = :tid AND document_id = :doc_id
            """),
            {"tid": tenant_id, "doc_id": document_id, "sid": subject_id, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT document_id, subject_id, upload_status, processing_status,
                           confirmation_status, source_channel, registered_at_utc
                    FROM docintel.documents
                    WHERE tenant_id = :tid AND document_id = :doc_id
                """),
                {"tid": tenant_id, "doc_id": document_id},
            )
        ).mappings().one()
    return _fmt_doc(updated)


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _fetch_unassigned_doc(session: Any, tenant_id: str, document_id: uuid.UUID) -> Any:
    return (
        await session.execute(
            text("""
                SELECT document_id, subject_id, upload_status, processing_status,
                       confirmation_status, source_channel, registered_at_utc,
                       content_state
                FROM docintel.documents
                WHERE tenant_id = :tid AND document_id = :doc_id
                  AND subject_id IS NULL
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).mappings().one_or_none()


async def _fetch_field_values(
    session: Any, tenant_id: str, document_id: uuid.UUID
) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT dfv.canonical_field_id, cf.field_key,
                       dfv.current_value, dfv.value_source,
                       dfv.confidence_score, dfv.version_no, dfv.is_current,
                       dfv.accepted_at_utc
                FROM docintel.document_field_values dfv
                JOIN docintel.canonical_fields cf
                  ON cf.canonical_field_id = dfv.canonical_field_id
                WHERE dfv.tenant_id = :tid AND dfv.document_id = :doc_id
                  AND dfv.is_current = true
                ORDER BY cf.field_key
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).mappings().all()
    return [
        {
            "canonicalFieldId": str(r["canonical_field_id"]),
            "fieldKey": r["field_key"],
            "currentValue": r["current_value"],
            "valueSource": r["value_source"],
            "confidenceScore": float(r["confidence_score"]) if r.get("confidence_score") else None,
            "versionNo": r["version_no"],
            "acceptedAt": r["accepted_at_utc"].isoformat() if r.get("accepted_at_utc") else None,
        }
        for r in rows
    ]


def _fmt_doc(r: Any) -> dict[str, Any]:
    return {
        "documentId": str(r["document_id"]),
        "subjectId": str(r["subject_id"]) if r.get("subject_id") else None,
        "uploadStatus": r["upload_status"],
        "processingStatus": r["processing_status"],
        "confirmationStatus": r["confirmation_status"],
        "sourceChannel": r.get("source_channel"),
        "registeredAt": r["registered_at_utc"].isoformat() if r.get("registered_at_utc") else None,
    }

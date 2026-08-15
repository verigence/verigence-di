"""api/v1/operations.py — Operations / Exceptions routes.

OAS operations:
  GET /v1/tenants/{tenantId}/document-exceptions
      → getTenantDocumentExceptions  (x-required-permissions: operations:read)
  GET /v1/tenants/{tenantId}/upload-quality
      → getUploadQuality             (x-required-permissions: operations:read)
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1", tags=["Operations"])
logger = structlog.get_logger(__name__)


# ── GET /v1/tenants/{tenantId}/document-exceptions ───────────────────────────

@router.get("/tenants/{tenant_id}/document-exceptions")
async def get_tenant_document_exceptions(
    tenant_id: str,
    subject_id: str | None = None,
    uploaded_by_actor_id: str | None = None,
    state: list[str] | None = None,
    include_resolved_history: bool = False,
    page: int = 1,
    page_size: int = 50,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.OPERATIONS_READ)),
) -> dict[str, Any]:
    """Tenant-wide document exception list."""
    default_states = [
        "NOT_FIT", "CORRUPT", "UPLOAD_FAILED", "RETRY_PENDING", "FAILED"
    ]
    active_states = state or default_states
    offset = (max(1, page) - 1) * min(200, page_size)
    limit = min(200, page_size)

    # Convert list to SQL array literal
    state_filter = "AND processing_status = ANY(:states)" if active_states else ""

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT d.document_id, d.subject_id, d.upload_status,
                           d.processing_status, d.confirmation_status,
                           d.upload_issue_code, d.processing_failure_code,
                           d.uploaded_by_actor_id, d.registered_at_utc
                    FROM docintel.documents d
                    WHERE d.tenant_id = :tid
                      AND (
                          d.upload_status IN ('NOT_FIT','CORRUPT','UPLOAD_FAILED')
                          OR d.processing_status IN ('RETRY_PENDING','FAILED')
                      )
                      AND (:sid IS NULL OR d.subject_id::text = :sid)
                      AND (:actor_id IS NULL OR d.uploaded_by_actor_id = :actor_id)
                      AND (:include_history OR d.replaced_by_document_id IS NULL)
                    ORDER BY d.registered_at_utc DESC
                    LIMIT :limit OFFSET :offset
                """),
                {
                    "tid": tenant_id,
                    "sid": subject_id,
                    "actor_id": uploaded_by_actor_id,
                    "include_history": include_resolved_history,
                    "limit": limit,
                    "offset": offset,
                },
            )
        ).mappings().all()

        total = (
            await session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM docintel.documents
                    WHERE tenant_id = :tid
                      AND (
                          upload_status IN ('NOT_FIT','CORRUPT','UPLOAD_FAILED')
                          OR processing_status IN ('RETRY_PENDING','FAILED')
                      )
                      AND (:include_history OR replaced_by_document_id IS NULL)
                """),
                {"tid": tenant_id, "include_history": include_resolved_history},
            )
        ).scalar()

    payload = {
        "items": [
            {
                "documentId": str(r["document_id"]),
                "subjectId": str(r["subject_id"]) if r.get("subject_id") else None,
                "uploadStatus": r["upload_status"],
                "processingStatus": r["processing_status"],
                "confirmationStatus": r["confirmation_status"],
                "issueCode": r.get("upload_issue_code") or r.get("processing_failure_code"),
                "uploadedByActorId": r["uploaded_by_actor_id"],
                "registeredAt": r["registered_at_utc"].isoformat() if r.get("registered_at_utc") else None,
            }
            for r in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total or 0,
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()


# ── GET /v1/tenants/{tenantId}/upload-quality ─────────────────────────────────

@router.get("/tenants/{tenant_id}/upload-quality")
async def get_upload_quality(
    tenant_id: str,
    uploaded_by_actor_id: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.OPERATIONS_READ)),
) -> dict[str, Any]:
    """Upload-quality metrics grouped by uploader."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT
                        uploaded_by_actor_id,
                        COUNT(*) AS total,
                        SUM(CASE WHEN upload_status = 'FIT' THEN 1 ELSE 0 END) AS fit,
                        SUM(CASE WHEN upload_status = 'NOT_FIT' THEN 1 ELSE 0 END) AS not_fit,
                        SUM(CASE WHEN upload_status = 'CORRUPT' THEN 1 ELSE 0 END) AS corrupt,
                        SUM(CASE WHEN upload_status = 'UPLOAD_FAILED' THEN 1 ELSE 0 END) AS upload_failed
                    FROM docintel.documents
                    WHERE tenant_id = :tid
                      AND (:actor_id IS NULL OR uploaded_by_actor_id = :actor_id)
                      AND (:from_dt IS NULL OR registered_at_utc >= CAST(:from_dt AS timestamptz))
                      AND (:to_dt IS NULL OR registered_at_utc <= CAST(:to_dt AS timestamptz))
                    GROUP BY uploaded_by_actor_id
                    ORDER BY total DESC
                """),
                {
                    "tid": tenant_id,
                    "actor_id": uploaded_by_actor_id,
                    "from_dt": from_,
                    "to_dt": to,
                },
            )
        ).mappings().all()

    items = [
        {
            "uploadedByActorId": r["uploaded_by_actor_id"],
            "total": r["total"],
            "fit": r["fit"],
            "notFit": r["not_fit"],
            "corrupt": r["corrupt"],
            "uploadFailed": r["upload_failed"],
            "firstPassFitRate": round(r["fit"] / r["total"] * 100, 2) if r["total"] else 0.0,
        }
        for r in rows
    ]
    return ApiResponse(errorCode="000", errorMessage="Success", data=items).model_dump()

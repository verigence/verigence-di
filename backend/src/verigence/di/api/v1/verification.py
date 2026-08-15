"""api/v1/verification.py — Human Verification routes.

OAS operations:
  POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}/verification
       → verifySubjectDocument  (x-required-permissions: verification:write)
  GET  /v1/tenants/{tenantId}/verification-queue
       → getVerificationQueue   (x-required-permissions: verification:read)
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1", tags=["Human Verification"])
logger = structlog.get_logger(__name__)


# ── GET /v1/tenants/{tenantId}/verification-queue ─────────────────────────────

@router.get(
    "/tenants/{tenant_id}/verification-queue",
    summary="Get Verification Queue",
    description=(
        "List CONFIRMED documents awaiting human verification, filtered by verification status. "
        "Required permission: `di.verification.read`. "
        "Returns D8 envelope with paginated items array."
    ),
    response_description="Verification queue",
    operation_id="getVerificationQueue",
)
async def get_verification_queue(
    tenant_id: str,
    human_verification_status: str = "MANDATORY",
    subject_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.VERIFICATION_READ)),
) -> dict[str, Any]:
    """List CONFIRMED documents awaiting human verification."""
    offset = (max(1, page) - 1) * min(200, page_size)
    limit = min(200, page_size)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT document_id, subject_id, document_type_id,
                           upload_status, processing_status, confirmation_status,
                           confidence_score, human_verification_status, verification_state,
                           registered_at_utc, updated_at_utc
                    FROM docintel.documents
                    WHERE tenant_id = :tid
                      AND confirmation_status = 'CONFIRMED'
                      AND verification_state = 'NOT_VERIFIED'
                      AND (:hvs IS NULL OR human_verification_status = :hvs)
                      AND (:sid IS NULL OR subject_id::text = :sid)
                    ORDER BY registered_at_utc DESC
                    LIMIT :limit OFFSET :offset
                """),
                {
                    "tid": tenant_id,
                    "hvs": human_verification_status,
                    "sid": subject_id,
                    "limit": limit,
                    "offset": offset,
                },
            )
        ).mappings().all()

        total_row = (
            await session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM docintel.documents
                    WHERE tenant_id = :tid
                      AND confirmation_status = 'CONFIRMED'
                      AND verification_state = 'NOT_VERIFIED'
                      AND (:hvs IS NULL OR human_verification_status = :hvs)
                """),
                {"tid": tenant_id, "hvs": human_verification_status},
            )
        ).scalar()

    payload = {
        "items": [_format_document(r) for r in rows],
        "page": page,
        "pageSize": page_size,
        "total": total_row or 0,
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()


# ── POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}/verification

@router.post(
    "/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}/verification",
    status_code=201,
    summary="Verify Document",
    description=(
        "Record a human verification decision for a CONFIRMED document. "
        "Optionally include fieldCorrections to override extracted field values. "
        "Required permission: `di.verification.write`. "
        "Returns D8 envelope with verificationId. "
        "Returns 409 if the document is not CONFIRMED or already VERIFIED."
    ),
    response_description="Verification record",
    operation_id="verifySubjectDocument",
)
async def verify_subject_document(
    tenant_id: str,
    subject_id: uuid.UUID,
    document_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.VERIFICATION_WRITE)),
) -> dict[str, Any]:
    """Record human verification and optional field corrections.

    Phase-1: one verification action per Document.
    Returns 409 INVALID_DOCUMENT_STATE if verificationState is already VERIFIED.
    """
    now = datetime.now(UTC)
    remarks: str | None = body.get("remarks")
    corrections: list[dict] = body.get("fieldCorrections") or []

    async with tenant_session(tenant_id) as session:
        doc_row = (
            await session.execute(
                text("""
                    SELECT document_id, confirmation_status, verification_state,
                           human_verification_status, confidence_score, subject_id
                    FROM docintel.documents
                    WHERE tenant_id = :tid
                      AND document_id = :doc_id
                      AND subject_id = :sid
                """),
                {"tid": tenant_id, "doc_id": document_id, "sid": subject_id},
            )
        ).mappings().one_or_none()

        if doc_row is None:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row["confirmation_status"] != "CONFIRMED":
            raise problem(409, "Document is not CONFIRMED — cannot verify",
                          ErrorCode.INVALID_DOCUMENT_STATE)
        if doc_row["verification_state"] == "VERIFIED":
            raise problem(409, "Document is already VERIFIED",
                          ErrorCode.INVALID_DOCUMENT_STATE)

        verification_id = uuid.uuid4()
        await session.execute(
            text("""
                INSERT INTO docintel.human_verifications
                    (tenant_id, verification_id, subject_id_at_time, document_id,
                     human_verification_status_at_time, machine_confidence_score,
                     verified_by_actor_id, remarks, verified_at_utc, created_at_utc)
                VALUES
                    (:tid, :vid, :sid, :doc_id,
                     :hvs, :conf,
                     :actor_id, :remarks, :now, :now)
            """),
            {
                "tid": tenant_id,
                "vid": verification_id,
                "sid": subject_id,
                "doc_id": document_id,
                "hvs": doc_row["human_verification_status"],
                "conf": float(doc_row["confidence_score"]),
                "actor_id": actor.actor_id,
                "remarks": remarks,
                "now": now,
            },
        )

        # Apply field corrections
        for corr in corrections:
            cf_id_str = corr.get("canonicalFieldId")
            new_value = corr.get("value")
            if not cf_id_str:
                continue

            # Mark prior current value non-current
            await session.execute(
                text("""
                    UPDATE docintel.document_field_values
                    SET is_current = false
                    WHERE tenant_id = :tid
                      AND document_id = :doc_id
                      AND canonical_field_id = :cf_id
                      AND is_current = true
                """),
                {"tid": tenant_id, "doc_id": document_id, "cf_id": cf_id_str},
            )
            # Get next version_no
            ver_row = (
                await session.execute(
                    text("""
                        SELECT COALESCE(MAX(version_no), 0) + 1
                        FROM docintel.document_field_values
                        WHERE tenant_id = :tid
                          AND document_id = :doc_id
                          AND canonical_field_id = :cf_id
                    """),
                    {"tid": tenant_id, "doc_id": document_id, "cf_id": cf_id_str},
                )
            ).scalar()

            await session.execute(
                text("""
                    INSERT INTO docintel.document_field_values
                        (tenant_id, document_field_value_id, document_id, canonical_field_id,
                         current_value, value_source, source_verification_id,
                         accepted_by_actor_id, accepted_at_utc,
                         version_no, is_current, created_at_utc)
                    VALUES
                        (:tid, :dfv_id, :doc_id, :cf_id,
                         CAST(:val AS jsonb), 'HUMAN', :vid,
                         :actor_id, :now,
                         :ver, true, :now)
                """),
                {
                    "tid": tenant_id,
                    "dfv_id": uuid.uuid4(),
                    "doc_id": document_id,
                    "cf_id": cf_id_str,
                    "val": json.dumps(new_value),
                    "vid": verification_id,
                    "actor_id": actor.actor_id,
                    "now": now,
                    "ver": ver_row or 2,
                },
            )

        # Set document verification_state = VERIFIED
        await session.execute(
            text("""
                UPDATE docintel.documents
                SET verification_state = 'VERIFIED', updated_at_utc = :now
                WHERE tenant_id = :tid AND document_id = :doc_id
            """),
            {"tid": tenant_id, "doc_id": document_id, "now": now},
        )
        await session.commit()

    logger.info(
        "document_verified",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        document_id=str(document_id),
        verification_id=str(verification_id),
    )

    payload = {
        "verificationId": str(verification_id),
        "documentId": str(document_id),
        "verifiedAt": now.isoformat(),
        "verifiedByActorId": actor.actor_id,
        "remarks": remarks,
        "fieldCorrectionCount": len(corrections),
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()


def _format_document(row: dict) -> dict[str, Any]:
    return {
        "documentId": str(row["document_id"]),
        "subjectId": str(row["subject_id"]) if row.get("subject_id") else None,
        "uploadStatus": row["upload_status"],
        "processingStatus": row["processing_status"],
        "confirmationStatus": row["confirmation_status"],
        "confidenceScore": float(row["confidence_score"]) if row.get("confidence_score") else None,
        "humanVerificationStatus": row.get("human_verification_status"),
        "verificationState": row["verification_state"],
        "registeredAt": row["registered_at_utc"].isoformat() if row.get("registered_at_utc") else None,
    }

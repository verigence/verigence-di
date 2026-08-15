"""api/v1/subject_matching.py — Subject identifier + WhatsApp sender mapping routes.

OAS operations (2):
  POST /v1/tenants/{tenantId}/subjects/{subjectId}/identifiers
       → addSubjectIdentifier    (subject_matching:write)
  POST /v1/tenants/{tenantId}/whatsapp/sender-mappings
       → putWhatsappSenderMapping (subject_matching:write)
"""
from __future__ import annotations

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

router = APIRouter(prefix="/v1", tags=["Subject Matching"])
logger = structlog.get_logger(__name__)


# ── POST /v1/tenants/{tenantId}/subjects/{subjectId}/identifiers ──────────────

@router.post(
    "/tenants/{tenant_id}/subjects/{subject_id}/identifiers",
    status_code=201,
)
async def add_subject_identifier(
    tenant_id: str,
    subject_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.SUBJECT_MATCHING_WRITE)
    ),
) -> dict[str, Any]:
    """Register a VERIFIED Subject identifier for deterministic WhatsApp matching.

    Creates only when no other active VERIFIED Subject in the Tenant owns the same
    identifier_type + normalized_value. Concurrent conflicts → 409 SUBJECT_IDENTIFIER_CONFLICT.
    """
    identifier_type: str = body.get("identifierType", "")
    normalized_value: str = body.get("normalizedValue", "")
    display_value: str | None = body.get("displayValue")

    if not identifier_type or not normalized_value:
        raise problem(422, "identifierType and normalizedValue are required",
                      ErrorCode.VALIDATION_ERROR)

    now = datetime.now(UTC)
    identifier_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        # Check subject exists
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

        # Uniqueness check: no other active VERIFIED Subject owns this type+value
        conflict = (
            await session.execute(
                text("""
                    SELECT si.subject_id
                    FROM docintel.subject_identifiers si
                    WHERE si.tenant_id = :tid
                      AND si.identifier_type = :itype
                      AND si.normalized_value = :nval
                      AND si.status = 'VERIFIED'
                      AND si.subject_id != :sid
                """),
                {
                    "tid": tenant_id, "itype": identifier_type,
                    "nval": normalized_value, "sid": subject_id,
                },
            )
        ).one_or_none()
        if conflict:
            raise problem(409,
                          "Another Subject already holds this identifier",
                          ErrorCode.SUBJECT_IDENTIFIER_CONFLICT)

        await session.execute(
            text("""
                INSERT INTO docintel.subject_identifiers
                    (tenant_id, identifier_id, subject_id, identifier_type,
                     normalized_value, display_value, status,
                     created_by_actor_id, created_at_utc, updated_at_utc)
                VALUES
                    (:tid, :iid, :sid, :itype, :nval, :dval, 'VERIFIED',
                     :actor_id, :now, :now)
                ON CONFLICT (tenant_id, identifier_type, normalized_value)
                DO UPDATE SET
                    subject_id = EXCLUDED.subject_id,
                    display_value = EXCLUDED.display_value,
                    updated_at_utc = EXCLUDED.updated_at_utc
            """),
            {
                "tid": tenant_id, "iid": identifier_id, "sid": subject_id,
                "itype": identifier_type, "nval": normalized_value,
                "dval": display_value, "actor_id": actor.actor_id, "now": now,
            },
        )
        await session.commit()

    logger.info(
        "subject_identifier_added",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        subject_id=str(subject_id),
        identifier_type=identifier_type,
    )

    payload = {
        "identifierId": str(identifier_id),
        "subjectId": str(subject_id),
        "identifierType": identifier_type,
        "normalizedValue": normalized_value,
        "displayValue": display_value,
        "status": "VERIFIED",
        "createdByActorId": actor.actor_id,
        "createdAt": now.isoformat(),
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()


# ── POST /v1/tenants/{tenantId}/whatsapp/sender-mappings ─────────────────────

@router.post("/tenants/{tenant_id}/whatsapp/sender-mappings")
async def put_whatsapp_sender_mapping(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.SUBJECT_MATCHING_WRITE)
    ),
) -> dict[str, Any]:
    """Create or update an exact WhatsApp sender-to-Subject mapping."""
    sender_phone_number: str = body.get("senderPhoneNumber", "")
    subject_id_str: str | None = body.get("subjectId")
    if not sender_phone_number:
        raise problem(422, "senderPhoneNumber is required", ErrorCode.VALIDATION_ERROR)

    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                INSERT INTO docintel.whatsapp_sender_mappings
                    (tenant_id, sender_phone_number, subject_id,
                     created_by_actor_id, status, created_at_utc, updated_at_utc)
                VALUES (:tid, :phone, :sid, :actor_id, 'ACTIVE', :now, :now)
                ON CONFLICT (tenant_id, sender_phone_number)
                DO UPDATE SET
                    subject_id = EXCLUDED.subject_id,
                    updated_at_utc = EXCLUDED.updated_at_utc
            """),
            {
                "tid": tenant_id, "phone": sender_phone_number,
                "sid": subject_id_str, "actor_id": actor.actor_id, "now": now,
            },
        )
        await session.commit()

    logger.info(
        "whatsapp_sender_mapped",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        sender_phone_number=sender_phone_number,
    )

    payload = {
        "tenantId": tenant_id,
        "senderPhoneNumber": sender_phone_number,
        "subjectId": subject_id_str,
        "status": "ACTIVE",
        "createdByActorId": actor.actor_id,
        "updatedAt": now.isoformat(),
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()

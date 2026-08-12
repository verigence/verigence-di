"""api/v1/entity_links.py — External Entity Link routes.

OAS operations:
  GET  /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}/entity-links
       → getDocumentEntityLinks  (x-required-permissions: entity_link:read)
  POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}/entity-links
       → addDocumentEntityLink   (x-required-permissions: entity_link:write)
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1", tags=["External Links"])

_PREFIX = "/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}/entity-links"


@router.get(_PREFIX)
async def get_document_entity_links(
    tenant_id: str,
    subject_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.ENTITY_LINK_READ)),
) -> list[dict[str, Any]]:
    """List active external entity links for a document."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT entity_link_id, link_type, external_entity_id,
                           external_system, description, created_by_actor_id,
                           created_at_utc
                    FROM docintel.entity_links
                    WHERE tenant_id = :tid
                      AND document_id = :doc_id
                      AND (subject_id = :sid OR subject_id IS NULL)
                      AND active = true
                    ORDER BY created_at_utc DESC
                """),
                {"tid": tenant_id, "doc_id": document_id, "sid": subject_id},
            )
        ).mappings().all()
    return [
        {
            "entityLinkId": str(r["entity_link_id"]),
            "linkType": r["link_type"],
            "externalEntityId": r["external_entity_id"],
            "externalSystem": r["external_system"],
            "description": r.get("description"),
            "createdByActorId": r["created_by_actor_id"],
            "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        }
        for r in rows
    ]


@router.post(_PREFIX, status_code=201)
async def add_document_entity_link(
    tenant_id: str,
    subject_id: uuid.UUID,
    document_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.ENTITY_LINK_WRITE)),
) -> dict[str, Any]:
    """Add a generic external entity link to a document."""
    link_type: str = body.get("linkType", "")
    external_entity_id: str = body.get("externalEntityId", "")
    external_system: str = body.get("externalSystem", "")
    description: str | None = body.get("description")

    if not link_type or not external_entity_id:
        raise problem(400, "linkType and externalEntityId are required",
                      ErrorCode.VALIDATION_ERROR)

    now = datetime.now(UTC)
    link_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        # Verify document exists in subject scope
        exists = (
            await session.execute(
                text("""
                    SELECT 1 FROM docintel.documents
                    WHERE tenant_id = :tid AND document_id = :doc_id AND subject_id = :sid
                """),
                {"tid": tenant_id, "doc_id": document_id, "sid": subject_id},
            )
        ).one_or_none()
        if not exists:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)

        await session.execute(
            text("""
                INSERT INTO docintel.entity_links
                    (tenant_id, entity_link_id, document_id, subject_id,
                     link_type, external_entity_id, external_system, description,
                     created_by_actor_id, active, created_at_utc)
                VALUES
                    (:tid, :lid, :doc_id, :sid,
                     :link_type, :ext_id, :ext_sys, :desc,
                     :actor_id, true, :now)
            """),
            {
                "tid": tenant_id,
                "lid": link_id,
                "doc_id": document_id,
                "sid": subject_id,
                "link_type": link_type,
                "ext_id": external_entity_id,
                "ext_sys": external_system,
                "desc": description,
                "actor_id": actor.actor_id,
                "now": now,
            },
        )
        await session.commit()

    return {
        "entityLinkId": str(link_id),
        "linkType": link_type,
        "externalEntityId": external_entity_id,
        "externalSystem": external_system,
        "description": description,
        "createdByActorId": actor.actor_id,
        "createdAt": now.isoformat(),
    }

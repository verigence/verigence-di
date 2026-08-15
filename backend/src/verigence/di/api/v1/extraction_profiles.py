"""api/v1/extraction_profiles.py — Document Types + Extraction Profiles + Rule catalog routes.

OAS operations (11):
  Document Types (4):
    GET  /v1/tenants/{tenantId}/document-types              → listDocumentTypes
    POST /v1/tenants/{tenantId}/document-types              → createDocumentType
    GET  /v1/tenants/{tenantId}/document-types/{key}        → getDocumentType
    PUT  /v1/tenants/{tenantId}/document-types/{key}        → updateDocumentType
  Extraction Profiles (5):
    GET  /v1/tenants/{tenantId}/document-types/{key}/extraction-profiles           → listExtractionProfiles
    POST /v1/tenants/{tenantId}/document-types/{key}/extraction-profiles           → createExtractionProfile
    GET  /v1/tenants/{tenantId}/document-types/{key}/extraction-profiles/{pid}     → getExtractionProfile
    PUT  /v1/tenants/{tenantId}/document-types/{key}/extraction-profiles/{pid}     → updateDraftExtractionProfile
    POST /v1/tenants/{tenantId}/document-types/{key}/extraction-profiles/{pid}/publish → publishExtractionProfile
  Rule Catalogs (2):
    GET  /v1/tenants/{tenantId}/normalization-rules         → listNormalizationRules
    GET  /v1/tenants/{tenantId}/validation-rules            → listValidationRules
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

router = APIRouter(prefix="/v1", tags=["Extraction Configuration"])
logger = structlog.get_logger(__name__)


# ── Document Types ────────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/document-types")
async def list_document_types(
    tenant_id: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    """List effective global + tenant Document Types."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT DISTINCT ON (dt.document_type_key)
                        dt.document_type_id, dt.document_type_key, dt.display_name,
                        dt.description, dt.status, dt.owner_tenant_id,
                        dt.created_at_utc, dt.updated_at_utc
                    FROM docintel.document_types dt
                    WHERE dt.status != 'RETIRED'
                      AND (dt.owner_tenant_id = :tid OR dt.owner_tenant_id IS NULL)
                    ORDER BY dt.document_type_key,
                             CASE WHEN dt.owner_tenant_id = :tid THEN 0 ELSE 1 END
                """),
                {"tid": tenant_id},
            )
        ).mappings().all()
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=[_fmt_doc_type(r) for r in rows],
    ).model_dump()


@router.post("/tenants/{tenant_id}/document-types", status_code=201)
async def create_document_type(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)
    ),
) -> dict[str, Any]:
    """Create a tenant-owned DRAFT Document Type."""
    key: str = body.get("documentTypeKey", "")
    display_name: str = body.get("displayName", key)
    description: str | None = body.get("description")
    if not key:
        raise problem(422, "documentTypeKey is required", ErrorCode.VALIDATION_ERROR)

    now = datetime.now(UTC)
    dt_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                text("""
                    SELECT 1 FROM docintel.document_types
                    WHERE document_type_key = :key AND owner_tenant_id = :tid
                """),
                {"key": key, "tid": tenant_id},
            )
        ).one_or_none()
        if existing:
            raise problem(409, f"Document Type key {key!r} already exists for this tenant",
                          ErrorCode.CONFLICT)

        await session.execute(
            text("""
                INSERT INTO docintel.document_types
                    (document_type_id, document_type_key, display_name, description,
                     status, owner_tenant_id, created_at_utc, updated_at_utc)
                VALUES (:dt_id, :key, :name, :desc, 'DRAFT', :tid, :now, :now)
            """),
            {
                "dt_id": dt_id, "key": key, "name": display_name,
                "desc": description, "tid": tenant_id, "now": now,
            },
        )
        await session.commit()
        row = (
            await session.execute(
                text("""
                    SELECT document_type_id, document_type_key, display_name,
                           description, status, owner_tenant_id,
                           created_at_utc, updated_at_utc
                    FROM docintel.document_types WHERE document_type_id = :dt_id
                """),
                {"dt_id": dt_id},
            )
        ).mappings().one()

    logger.info(
        "extraction_profile_created",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        document_type_key=key,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_doc_type(row)).model_dump()


@router.get("/tenants/{tenant_id}/document-types/{document_type_key}")
async def get_document_type(
    tenant_id: str,
    document_type_key: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT DISTINCT ON (dt.document_type_key)
                        dt.document_type_id, dt.document_type_key, dt.display_name,
                        dt.description, dt.status, dt.owner_tenant_id,
                        dt.created_at_utc, dt.updated_at_utc
                    FROM docintel.document_types dt
                    WHERE dt.document_type_key = :key
                      AND (dt.owner_tenant_id = :tid OR dt.owner_tenant_id IS NULL)
                    ORDER BY dt.document_type_key,
                             CASE WHEN dt.owner_tenant_id = :tid THEN 0 ELSE 1 END
                """),
                {"key": document_type_key, "tid": tenant_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise problem(404, "Document Type not found", ErrorCode.DOCUMENT_TYPE_NOT_FOUND)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_doc_type(row)).model_dump()


@router.put("/tenants/{tenant_id}/document-types/{document_type_key}")
async def update_document_type(
    tenant_id: str,
    document_type_key: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)
    ),
) -> dict[str, Any]:
    """Update display_name/description of a tenant-owned DRAFT Document Type."""
    now = datetime.now(UTC)
    display_name: str | None = body.get("displayName")
    description: str | None = body.get("description")

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT document_type_id, status FROM docintel.document_types
                    WHERE document_type_key = :key AND owner_tenant_id = :tid
                """),
                {"key": document_type_key, "tid": tenant_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Document Type not found", ErrorCode.DOCUMENT_TYPE_NOT_FOUND)
        if row[1] == "RETIRED":
            raise problem(409, "Cannot update a RETIRED Document Type",
                          ErrorCode.INVALID_DOCUMENT_TYPE_STATE)

        await session.execute(
            text("""
                UPDATE docintel.document_types
                SET display_name = COALESCE(:name, display_name),
                    description = :desc,
                    updated_at_utc = :now
                WHERE document_type_id = :dt_id
            """),
            {"dt_id": row[0], "name": display_name, "desc": description, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT document_type_id, document_type_key, display_name,
                           description, status, owner_tenant_id,
                           created_at_utc, updated_at_utc
                    FROM docintel.document_types WHERE document_type_id = :dt_id
                """),
                {"dt_id": row[0]},
            )
        ).mappings().one()

    logger.info(
        "extraction_profile_created",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        document_type_key=document_type_key,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_doc_type(updated)).model_dump()


# ── Extraction Profiles ───────────────────────────────────────────────────────

@router.get(
    "/tenants/{tenant_id}/document-types/{document_type_key}/extraction-profiles"
)
async def list_extraction_profiles(
    tenant_id: str,
    document_type_key: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT ep.profile_id, ep.version_no, ep.profile_name,
                           ep.status, ep.scope_tenant_id,
                           ep.created_by_actor_id, ep.published_by_actor_id,
                           ep.created_at_utc, ep.published_at_utc, ep.updated_at_utc
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    WHERE dt.document_type_key = :key
                      AND (ep.scope_tenant_id = :tid OR ep.scope_tenant_id IS NULL)
                    ORDER BY ep.version_no DESC
                """),
                {"key": document_type_key, "tid": tenant_id},
            )
        ).mappings().all()
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=[_fmt_extraction_profile(r) for r in rows],
    ).model_dump()


@router.post(
    "/tenants/{tenant_id}/document-types/{document_type_key}/extraction-profiles",
    status_code=201,
)
async def create_extraction_profile(
    tenant_id: str,
    document_type_key: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)
    ),
) -> dict[str, Any]:
    """Create a DRAFT Extraction Profile for a Document Type."""
    profile_name: str = body.get("profileName", f"Profile for {document_type_key}")
    now = datetime.now(UTC)
    profile_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        dt_row = (
            await session.execute(
                text("""
                    SELECT DISTINCT ON (dt.document_type_key) dt.document_type_id
                    FROM docintel.document_types dt
                    WHERE dt.document_type_key = :key
                      AND (dt.owner_tenant_id = :tid OR dt.owner_tenant_id IS NULL)
                    ORDER BY dt.document_type_key,
                             CASE WHEN dt.owner_tenant_id = :tid THEN 0 ELSE 1 END
                """),
                {"key": document_type_key, "tid": tenant_id},
            )
        ).one_or_none()
        if dt_row is None:
            raise problem(404, "Document Type not found", ErrorCode.DOCUMENT_TYPE_NOT_FOUND)
        dt_id = dt_row[0]

        # Next version_no for this type+scope
        ver_row = (
            await session.execute(
                text("""
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM docintel.extraction_profiles
                    WHERE document_type_id = :dtid
                      AND COALESCE(scope_tenant_id, '__GLOBAL__') =
                          COALESCE(:tid, '__GLOBAL__')
                """),
                {"dtid": dt_id, "tid": tenant_id},
            )
        ).scalar()

        await session.execute(
            text("""
                INSERT INTO docintel.extraction_profiles
                    (profile_id, document_type_id, scope_tenant_id, version_no,
                     profile_name, status, created_by_actor_id,
                     created_at_utc, updated_at_utc)
                VALUES (:pid, :dtid, :tid, :ver, :name, 'DRAFT', :actor_id, :now, :now)
            """),
            {
                "pid": profile_id, "dtid": dt_id, "tid": tenant_id,
                "ver": ver_row or 1, "name": profile_name,
                "actor_id": actor.actor_id, "now": now,
            },
        )
        await session.commit()
        row = (
            await session.execute(
                text("""
                    SELECT profile_id, version_no, profile_name, status,
                           scope_tenant_id, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.extraction_profiles WHERE profile_id = :pid
                """),
                {"pid": profile_id},
            )
        ).mappings().one()

    logger.info(
        "extraction_profile_created",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        profile_id=str(profile_id),
        document_type_key=document_type_key,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_extraction_profile(row)).model_dump()


@router.get(
    "/tenants/{tenant_id}/document-types/{document_type_key}/extraction-profiles/{profile_id}"
)
async def get_extraction_profile(
    tenant_id: str,
    document_type_key: str,
    profile_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT ep.profile_id, ep.version_no, ep.profile_name, ep.status,
                           ep.scope_tenant_id, ep.created_by_actor_id,
                           ep.published_by_actor_id,
                           ep.created_at_utc, ep.published_at_utc, ep.updated_at_utc
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    WHERE ep.profile_id = :pid
                      AND dt.document_type_key = :key
                      AND (ep.scope_tenant_id = :tid OR ep.scope_tenant_id IS NULL)
                """),
                {"pid": profile_id, "key": document_type_key, "tid": tenant_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise problem(404, "Extraction Profile not found",
                      ErrorCode.EXTRACTION_PROFILE_NOT_FOUND)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_extraction_profile(row)).model_dump()


@router.put(
    "/tenants/{tenant_id}/document-types/{document_type_key}/extraction-profiles/{profile_id}"
)
async def update_draft_extraction_profile(
    tenant_id: str,
    document_type_key: str,
    profile_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)
    ),
) -> dict[str, Any]:
    """Replace contents of a DRAFT Extraction Profile."""
    now = datetime.now(UTC)
    profile_name: str | None = body.get("profileName")
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT ep.status FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    WHERE ep.profile_id = :pid AND dt.document_type_key = :key
                      AND (ep.scope_tenant_id = :tid OR ep.scope_tenant_id IS NULL)
                """),
                {"pid": profile_id, "key": document_type_key, "tid": tenant_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Extraction Profile not found",
                          ErrorCode.EXTRACTION_PROFILE_NOT_FOUND)
        if row[0] != "DRAFT":
            raise problem(409, "Only DRAFT profiles may be updated",
                          ErrorCode.INVALID_PROFILE_STATE)

        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET profile_name = COALESCE(:name, profile_name), updated_at_utc = :now
                WHERE profile_id = :pid
            """),
            {"pid": profile_id, "name": profile_name, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT profile_id, version_no, profile_name, status,
                           scope_tenant_id, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.extraction_profiles WHERE profile_id = :pid
                """),
                {"pid": profile_id},
            )
        ).mappings().one()

    logger.info(
        "extraction_profile_created",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        profile_id=str(profile_id),
        document_type_key=document_type_key,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_extraction_profile(updated)).model_dump()


@router.post(
    "/tenants/{tenant_id}/document-types/{document_type_key}/extraction-profiles/{profile_id}/publish"
)
async def publish_extraction_profile(
    tenant_id: str,
    document_type_key: str,
    profile_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_PUBLISH)
    ),
) -> dict[str, Any]:
    """Publish DRAFT; atomically retire previous PUBLISHED for the same type+scope."""
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT ep.status, ep.document_type_id, ep.scope_tenant_id
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    WHERE ep.profile_id = :pid AND dt.document_type_key = :key
                      AND (ep.scope_tenant_id = :tid OR ep.scope_tenant_id IS NULL)
                """),
                {"pid": profile_id, "key": document_type_key, "tid": tenant_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Extraction Profile not found",
                          ErrorCode.EXTRACTION_PROFILE_NOT_FOUND)
        if row[0] != "DRAFT":
            raise problem(409, "Only DRAFT profiles may be published",
                          ErrorCode.INVALID_PROFILE_STATE)
        dt_id = row[1]
        scope = row[2]

        # Retire existing PUBLISHED for same type+scope
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status = 'RETIRED', updated_at_utc = :now
                WHERE document_type_id = :dtid
                  AND COALESCE(scope_tenant_id, '__GLOBAL__') =
                      COALESCE(:scope, '__GLOBAL__')
                  AND status = 'PUBLISHED'
            """),
            {"dtid": dt_id, "scope": scope, "now": now},
        )
        # Activate document type if DRAFT
        await session.execute(
            text("""
                UPDATE docintel.document_types
                SET status = 'ACTIVE', updated_at_utc = :now
                WHERE document_type_id = :dtid AND status = 'DRAFT'
            """),
            {"dtid": dt_id, "now": now},
        )
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status = 'PUBLISHED',
                    published_by_actor_id = :actor_id,
                    published_at_utc = :now,
                    updated_at_utc = :now
                WHERE profile_id = :pid
            """),
            {"pid": profile_id, "actor_id": actor.actor_id, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT profile_id, version_no, profile_name, status,
                           scope_tenant_id, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.extraction_profiles WHERE profile_id = :pid
                """),
                {"pid": profile_id},
            )
        ).mappings().one()

    logger.info(
        "extraction_profile_published",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        profile_id=str(profile_id),
        document_type_key=document_type_key,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_extraction_profile(updated)).model_dump()


# ── Rule Catalogs ─────────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/normalization-rules")
async def list_normalization_rules(
    tenant_id: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT rule_key, description, implementation_key,
                           parameter_schema, status
                    FROM docintel.normalization_rule_catalog
                    WHERE status = 'ACTIVE'
                    ORDER BY rule_key
                """),
            )
        ).mappings().all()
    items = [
        {
            "ruleKey": r["rule_key"],
            "description": r["description"],
            "implementationKey": r["implementation_key"],
            "parameterSchema": r["parameter_schema"],
            "status": r["status"],
        }
        for r in rows
    ]
    return ApiResponse(errorCode="000", errorMessage="Success", data=items).model_dump()


@router.get("/tenants/{tenant_id}/validation-rules")
async def list_validation_rules(
    tenant_id: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT rule_key, description, implementation_key,
                           parameter_schema, result_scope, status
                    FROM docintel.validation_rule_catalog
                    WHERE status = 'ACTIVE'
                    ORDER BY rule_key
                """),
            )
        ).mappings().all()
    items = [
        {
            "ruleKey": r["rule_key"],
            "description": r["description"],
            "implementationKey": r["implementation_key"],
            "parameterSchema": r["parameter_schema"],
            "resultScope": r["result_scope"],
            "status": r["status"],
        }
        for r in rows
    ]
    return ApiResponse(errorCode="000", errorMessage="Success", data=items).model_dump()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_doc_type(r: Any) -> dict[str, Any]:
    return {
        "documentTypeId": str(r["document_type_id"]),
        "documentTypeKey": r["document_type_key"],
        "displayName": r["display_name"],
        "description": r.get("description"),
        "status": r["status"],
        "ownerTenantId": r.get("owner_tenant_id"),
        "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        "updatedAt": r["updated_at_utc"].isoformat() if r.get("updated_at_utc") else None,
    }


def _fmt_extraction_profile(r: Any) -> dict[str, Any]:
    return {
        "profileId": str(r["profile_id"]),
        "versionNo": r["version_no"],
        "profileName": r["profile_name"],
        "status": r["status"],
        "scopeTenantId": r.get("scope_tenant_id"),
        "createdByActorId": r["created_by_actor_id"],
        "publishedByActorId": r.get("published_by_actor_id"),
        "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        "publishedAt": r["published_at_utc"].isoformat() if r.get("published_at_utc") else None,
        "updatedAt": r["updated_at_utc"].isoformat() if r.get("updated_at_utc") else None,
    }

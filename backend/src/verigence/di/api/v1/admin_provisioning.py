"""UC02 DI Tenant provisioning, effective defaults and Project purge APIs."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.human_admin import HumanAdminRequest, require_uc02_super_admin
from verigence.di.repositories.database import get_db_session, set_tenant_context
from verigence.di.repositories.tenants import (
    provision_retention_policy,
    provision_tenant,
    provision_tenant_document_types,
)
from verigence.di.storage.adapter import get_storage_adapter

admin_router = APIRouter(prefix="/v1/tenants/{tenantId}/admin", tags=["UC02 Administration"])
effective_master_router = APIRouter(
    prefix="/v1/tenants/{tenantId}/project-masters",
    tags=["UC02 Project Masters"],
)


class ProvisioningCheck(BaseModel):
    key: str
    status: Literal["PASS", "FAIL"]
    message: str


class ProvisioningData(BaseModel):
    tenantId: str
    provisioningStatus: Literal["READY", "INCOMPLETE"]
    checks: list[ProvisioningCheck]


class ProvisioningCleanupData(BaseModel):
    tenantId: str
    provisioningStatus: Literal["REMOVED"]


class ProjectPurgeData(BaseModel):
    tenantId: str
    purgeStatus: Literal["REMOVED"]
    deletedStorageObjects: int


async def _status(session: AsyncSession, tenant_id: str) -> ProvisioningData:
    await set_tenant_context(session, tenant_id)
    settings_exists = bool(
        (
            await session.execute(
                text("SELECT EXISTS (SELECT 1 FROM docintel.tenant_settings WHERE tenant_id=:tid)"),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )
    retention_exists = False
    document_type_count = 0
    if settings_exists:
        retention_exists = bool(
            (
                await session.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM docintel.tenant_settings ts
                            JOIN docintel.retention_policies rp
                              ON rp.tenant_id=ts.tenant_id
                             AND rp.retention_policy_id=ts.active_retention_policy_id
                            WHERE ts.tenant_id=:tid AND rp.status='ACTIVE'
                        )
                        """
                    ),
                    {"tid": tenant_id},
                )
            ).scalar_one()
        )
        document_type_count = int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM docintel.tenant_document_types "
                        "WHERE tenant_id=:tid"
                    ),
                    {"tid": tenant_id},
                )
            ).scalar_one()
        )

    checks = [
        ProvisioningCheck(
            key="tenant_settings",
            status="PASS" if settings_exists else "FAIL",
            message="Tenant settings exist." if settings_exists else "Tenant settings are missing.",
        ),
        ProvisioningCheck(
            key="active_retention_policy",
            status="PASS" if retention_exists else "FAIL",
            message=(
                "An active retention policy is linked."
                if retention_exists
                else "An active retention policy is not linked."
            ),
        ),
        ProvisioningCheck(
            key="tenant_document_types",
            status="PASS" if document_type_count > 0 else "FAIL",
            message=(
                "Tenant Document Types are provisioned."
                if document_type_count > 0
                else "Tenant Document Types are not provisioned."
            ),
        ),
    ]
    ready = all(check.status == "PASS" for check in checks)
    return ProvisioningData(
        tenantId=tenant_id,
        provisioningStatus="READY" if ready else "INCOMPLETE",
        checks=checks,
    )


@admin_router.put("/provisioning", response_model=ApiResponse[ProvisioningData])
async def ensure_provisioning(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> ApiResponse[ProvisioningData]:
    del admin, idempotency_key
    await set_tenant_context(session, tenantId)
    await provision_tenant(session, tenantId)
    await provision_retention_policy(session, tenantId)
    await provision_tenant_document_types(session, tenantId)
    data = await _status(session, tenantId)
    if data.provisioningStatus != "READY":
        raise RuntimeError("DI Tenant provisioning did not reach READY state")
    return ApiResponse(errorCode="000", errorMessage="Success", data=data)


@admin_router.get("/provisioning", response_model=ApiResponse[ProvisioningData])
async def get_provisioning(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[ProvisioningData]:
    del admin
    data = await _status(session, tenantId)
    return ApiResponse(errorCode="000", errorMessage="Success", data=data)


@admin_router.delete("/provisioning", response_model=ApiResponse[ProvisioningCleanupData])
async def remove_provisioning(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[ProvisioningCleanupData]:
    """Narrow compensation for failed new-Project provisioning only."""
    del admin
    await set_tenant_context(session, tenantId)
    has_documents = bool(
        (
            await session.execute(
                text("SELECT EXISTS (SELECT 1 FROM docintel.documents WHERE tenant_id=:tid)"),
                {"tid": tenantId},
            )
        ).scalar_one()
    )
    if has_documents:
        raise HTTPException(
            status_code=409,
            detail="Tenant provisioning cannot be compensated after operational data exists.",
        )

    await session.execute(
        text("DELETE FROM docintel.tenant_document_types WHERE tenant_id=:tid"),
        {"tid": tenantId},
    )
    await session.execute(
        text(
            "UPDATE docintel.tenant_settings "
            "SET active_retention_policy_id=NULL WHERE tenant_id=:tid"
        ),
        {"tid": tenantId},
    )
    await session.execute(
        text("DELETE FROM docintel.retention_policies WHERE tenant_id=:tid"),
        {"tid": tenantId},
    )
    await session.execute(
        text("DELETE FROM docintel.tenant_settings WHERE tenant_id=:tid"),
        {"tid": tenantId},
    )

    remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM docintel.tenant_settings WHERE tenant_id=:tid) +
                      (SELECT count(*) FROM docintel.retention_policies WHERE tenant_id=:tid) +
                      (SELECT count(*) FROM docintel.tenant_document_types WHERE tenant_id=:tid)
                    """
                ),
                {"tid": tenantId},
            )
        ).scalar_one()
    )
    if remaining != 0:
        raise RuntimeError("DI Tenant provisioning compensation did not reach zero state")

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=ProvisioningCleanupData(tenantId=tenantId, provisioningStatus="REMOVED"),
    )


async def _effective_versions(
    session: AsyncSession,
    *,
    tenant_id: str,
    master_key: str,
) -> list[dict[str, Any]]:
    await set_tenant_context(session, tenant_id)
    if master_key == "DOCUMENT_TYPES":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT dt.document_type_id AS version_id,
                           dt.document_type_key AS business_key,
                           dt.display_name,
                           dt.status,
                           NULL::integer AS version_no,
                           dt.created_at_utc,
                           dt.updated_at_utc,
                           tdt.physical_form_type,
                           tdt.requires_processing,
                           tdt.display_order,
                           COALESCE(tdt.is_active, false) AS is_active,
                           CASE WHEN dt.owner_tenant_id IS NULL
                                THEN 'VERIGENCE_DEFAULT' ELSE 'PROJECT_CUSTOM' END
                                AS configuration_source,
                           (dt.owner_tenant_id IS NULL) AS inherited
                    FROM docintel.document_types dt
                    LEFT JOIN docintel.tenant_document_types tdt
                      ON tdt.tenant_id=:tenant_id
                     AND tdt.document_type_id=dt.document_type_id
                    WHERE (
                        dt.owner_tenant_id=:tenant_id
                        OR (
                            dt.owner_tenant_id IS NULL
                            AND dt.status='ACTIVE'
                            AND COALESCE(tdt.is_active, false)=true
                        )
                    )
                    ORDER BY inherited DESC, dt.document_type_key, dt.updated_at_utc DESC
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        return [
            {
                "versionId": row["version_id"],
                "businessKey": row["business_key"],
                "displayName": row["display_name"],
                "status": row["status"],
                "versionNo": row["version_no"],
                "createdAtUtc": row["created_at_utc"],
                "updatedAtUtc": row["updated_at_utc"],
                "physicalFormType": row["physical_form_type"],
                "requiresProcessing": row["requires_processing"],
                "displayOrder": row["display_order"],
                "activeForTenant": bool(row["is_active"]),
                "configurationSource": row["configuration_source"],
                "inherited": bool(row["inherited"]),
            }
            for row in rows
        ]

    if master_key == "EXTRACTION_PROFILES":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT ep.profile_id AS version_id,
                           dt.document_type_key AS business_key,
                           ep.profile_name AS display_name,
                           ep.status,
                           ep.version_no,
                           ep.created_at_utc,
                           ep.updated_at_utc,
                           ep.published_at_utc,
                           CASE WHEN ep.scope_tenant_id IS NULL
                                THEN 'VERIGENCE_DEFAULT' ELSE 'PROJECT_CUSTOM' END
                                AS configuration_source,
                           (ep.scope_tenant_id IS NULL) AS inherited
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt
                      ON dt.document_type_id=ep.document_type_id
                    WHERE ep.scope_tenant_id=:tenant_id
                       OR (
                           ep.scope_tenant_id IS NULL
                           AND ep.status='PUBLISHED'
                           AND EXISTS (
                               SELECT 1
                               FROM docintel.tenant_document_types tdt
                               WHERE tdt.tenant_id=:tenant_id
                                 AND tdt.document_type_id=ep.document_type_id
                                 AND tdt.is_active=true
                           )
                       )
                    ORDER BY inherited DESC, dt.document_type_key, ep.version_no DESC
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        return [
            {
                "versionId": row["version_id"],
                "businessKey": row["business_key"],
                "displayName": row["display_name"],
                "status": row["status"],
                "versionNo": row["version_no"],
                "createdAtUtc": row["created_at_utc"],
                "updatedAtUtc": row["updated_at_utc"],
                "publishedAtUtc": row["published_at_utc"],
                "configurationSource": row["configuration_source"],
                "inherited": bool(row["inherited"]),
            }
            for row in rows
        ]

    if master_key == "REQUIREMENT_PROFILES":
        rows = (
            await session.execute(
                text(
                    """
                    SELECT rp.requirement_profile_id AS version_id,
                           rp.profile_key AS business_key,
                           rp.profile_key AS display_name,
                           rp.status,
                           rp.version_no,
                           rp.created_at_utc,
                           rp.updated_at_utc,
                           rp.published_at_utc
                    FROM docintel.document_requirement_profiles rp
                    WHERE rp.tenant_id=:tenant_id
                    ORDER BY rp.profile_key, rp.version_no DESC
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        return [
            {
                "versionId": row["version_id"],
                "businessKey": row["business_key"],
                "displayName": row["display_name"],
                "status": row["status"],
                "versionNo": row["version_no"],
                "createdAtUtc": row["created_at_utc"],
                "updatedAtUtc": row["updated_at_utc"],
                "publishedAtUtc": row["published_at_utc"],
                "configurationSource": "PROJECT_CUSTOM",
                "inherited": False,
            }
            for row in rows
        ]

    raise HTTPException(status_code=422, detail="Unsupported DI Project Master key.")


@effective_master_router.get("/{masterKey}/versions")
async def list_effective_project_master_versions(
    tenantId: str,
    masterKey: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[dict[str, Any]]:
    del admin
    key = masterKey.strip().upper().replace("-", "_")
    versions = await _effective_versions(session, tenant_id=tenantId, master_key=key)
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data={"masterKey": key, "versions": versions},
    )


@admin_router.delete("/project-data", response_model=ApiResponse[ProjectPurgeData])
async def purge_project_data(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[ProjectPurgeData]:
    """Hard-delete Project-owned DI state. Audit Core owns the zero-Journey gate.

    This endpoint is deliberately SuperAdmin-only and idempotent. Object storage
    is deleted before database state so retries remain safe after partial failure.
    Global Verigence Document Types and extraction profiles are never deleted.
    """
    del admin
    await set_tenant_context(session, tenantId)
    artifact_keys = [
        str(value)
        for value in (
            await session.execute(
                text(
                    "SELECT logical_object_key FROM docintel.document_artifacts "
                    "WHERE tenant_id=:tid AND logical_object_key IS NOT NULL"
                ),
                {"tid": tenantId},
            )
        ).scalars().all()
    ]
    storage = get_storage_adapter()
    for logical_key in artifact_keys:
        await storage.delete(logical_key)

    # Remove tenant-owned profile children that do not themselves carry tenant_id.
    await session.execute(
        text(
            """
            DELETE FROM docintel.extraction_profile_fields
            WHERE profile_id IN (
                SELECT profile_id FROM docintel.extraction_profiles
                WHERE scope_tenant_id=:tid
            )
            """
        ),
        {"tid": tenantId},
    )

    # tenant_settings points at its active retention policy while the retention
    # policy also belongs to the same Tenant. Break this deliberate ownership cycle
    # before generic FK child-first cleanup, mirroring provisioning compensation.
    await session.execute(
        text(
            "UPDATE docintel.tenant_settings "
            "SET active_retention_policy_id=NULL WHERE tenant_id=:tid"
        ),
        {"tid": tenantId},
    )

    # Delete every tenant-scoped table in FK-child-first order. This intentionally
    # adapts to additive DI tables while remaining restricted to docintel + tenant_id.
    await session.execute(
        text(
            """
            DO $$
            DECLARE target record;
            BEGIN
              FOR target IN
                WITH RECURSIVE tenant_tables AS (
                  SELECT c.oid, c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid=c.relnamespace
                  JOIN pg_attribute a ON a.attrelid=c.oid
                  WHERE n.nspname='docintel'
                    AND c.relkind='r'
                    AND a.attname='tenant_id'
                    AND a.attnum > 0
                    AND NOT a.attisdropped
                ),
                edges AS (
                  SELECT con.conrelid AS child, con.confrelid AS parent
                  FROM pg_constraint con
                  WHERE con.contype='f'
                    AND con.conrelid IN (SELECT oid FROM tenant_tables)
                    AND con.confrelid IN (SELECT oid FROM tenant_tables)
                    AND con.conrelid <> con.confrelid
                ),
                walk(child, parent, depth, path) AS (
                  SELECT child, parent, 1, ARRAY[child, parent]::oid[] FROM edges
                  UNION ALL
                  SELECT w.child, e.parent, w.depth + 1, w.path || e.parent
                  FROM walk w
                  JOIN edges e ON e.child=w.parent
                  WHERE NOT e.parent = ANY(w.path)
                ),
                depths AS (
                  SELECT t.oid, t.relname, COALESCE(max(w.depth), 0) AS depth
                  FROM tenant_tables t
                  LEFT JOIN walk w ON w.child=t.oid
                  GROUP BY t.oid, t.relname
                )
                SELECT relname FROM depths ORDER BY depth DESC, relname
              LOOP
                EXECUTE format(
                  'DELETE FROM docintel.%I WHERE tenant_id = %L',
                  target.relname,
                  current_setting('app.tenant_id')
                );
              END LOOP;
            END $$;
            """
        )
    )

    # Tenant custom extraction/document definitions use ownership columns instead
    # of tenant_id and therefore require explicit cleanup after tenant links are gone.
    await session.execute(
        text("DELETE FROM docintel.extraction_profiles WHERE scope_tenant_id=:tid"),
        {"tid": tenantId},
    )
    await session.execute(
        text("DELETE FROM docintel.document_types WHERE owner_tenant_id=:tid"),
        {"tid": tenantId},
    )

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=ProjectPurgeData(
            tenantId=tenantId,
            purgeStatus="REMOVED",
            deletedStorageObjects=len(artifact_keys),
        ),
    )


# Composite router keeps main.py unchanged while allowing the effective-version
# route to be registered before the legacy project_masters router.
router = APIRouter()
router.include_router(admin_router)
router.include_router(effective_master_router)

"""UC02 synchronous DI Tenant provisioning ensure/status/compensation API."""
from __future__ import annotations

from typing import Annotated, Literal

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

router = APIRouter(prefix="/v1/tenants/{tenantId}/admin", tags=["UC02 Administration"])


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


@router.put("/provisioning", response_model=ApiResponse[ProvisioningData])
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


@router.get("/provisioning", response_model=ApiResponse[ProvisioningData])
async def get_provisioning(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[ProvisioningData]:
    del admin
    data = await _status(session, tenantId)
    return ApiResponse(errorCode="000", errorMessage="Success", data=data)


@router.delete("/provisioning", response_model=ApiResponse[ProvisioningCleanupData])
async def remove_provisioning(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[ProvisioningCleanupData]:
    """Synchronously remove UC02 provisioning state for a failed new-Project create.

    This is intentionally narrow compensation, not a Tenant purge API. It refuses
    cleanup once DI document/operational data exists for the Tenant. The request
    transaction rolls back automatically if any delete or zero-state check fails.
    """
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

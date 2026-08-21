"""UC02 trusted Audit Core storage-context API."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.service_integration import (
    ServiceIntegrationPrincipal,
    require_service_integration,
)
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.audit_storage_contexts import (
    AuditStorageContextConflict,
    ensure_audit_storage_context,
)
from verigence.di.repositories.database import get_db_session, set_tenant_context
from verigence.di.repositories.subjects import subject_exists
from verigence.di.storage.audit_keys import frozen_audit_slugs

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["Audit Storage Contexts"])


class AuditDisplayContext(BaseModel):
    projectName: str | None = None
    dealerName: str | None = None
    dealerOutletName: str | None = None
    customerName: str | None = None


class EnsureAuditStorageContextRequest(BaseModel):
    subjectId: UUID
    dealerId: UUID
    dealerOutletId: UUID
    customerId: UUID
    displayContext: AuditDisplayContext = AuditDisplayContext()


class AuditStorageContextData(BaseModel):
    storageContextId: UUID
    externalContextRef: str
    subjectId: UUID
    dealerId: UUID
    dealerOutletId: UUID
    customerId: UUID


@router.put(
    "/audit-storage-contexts/{externalContextRef}",
    response_model=ApiResponse[AuditStorageContextData],
    summary="Ensure trusted Audit storage context",
)
async def ensure_storage_context(
    tenantId: str,
    externalContextRef: str,
    request: EnsureAuditStorageContextRequest,
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> ApiResponse[AuditStorageContextData]:
    # Header is mandatory by D28/LLD. externalContextRef is the stable semantic identity.
    del idempotency_key
    external_ref = externalContextRef.strip()
    if not external_ref:
        raise http_exception(ErrorCode.INVALID_REQUEST, detail="externalContextRef is required.")

    await set_tenant_context(session, tenantId)
    tenant_exists = (
        await session.execute(
            text("SELECT 1 FROM docintel.tenant_settings WHERE tenant_id=:tenant_id"),
            {"tenant_id": tenantId},
        )
    ).scalar_one_or_none()
    if tenant_exists is None:
        raise http_exception(ErrorCode.TENANT_NOT_FOUND)
    if not await subject_exists(session, tenant_id=tenantId, subject_id=request.subjectId):
        raise http_exception(ErrorCode.SUBJECT_NOT_FOUND)

    slugs = frozen_audit_slugs(
        tenant_id=tenantId,
        project_name=request.displayContext.projectName,
        dealer_name=request.displayContext.dealerName,
        dealer_outlet_name=request.displayContext.dealerOutletName,
        customer_name=request.displayContext.customerName,
    )
    try:
        context = await ensure_audit_storage_context(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            subject_id=request.subjectId,
            dealer_id=request.dealerId,
            dealer_outlet_id=request.dealerOutletId,
            customer_id=request.customerId,
            service_principal_id=service.service_id,
            project_slug=slugs[0],
            dealer_slug=slugs[1],
            dealer_outlet_slug=slugs[2],
            customer_slug=slugs[3],
        )
    except AuditStorageContextConflict as exc:
        raise http_exception(ErrorCode.CONFLICT, detail=str(exc)) from exc

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=AuditStorageContextData(
            storageContextId=context["storage_context_id"],
            externalContextRef=str(context["external_context_ref"]),
            subjectId=context["subject_id"],
            dealerId=context["dealer_id"],
            dealerOutletId=context["dealer_outlet_id"],
            customerId=context["customer_id"],
        ),
    )

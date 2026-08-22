"""UC02 trusted Audit Core storage-context and document-intake API."""
from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v1.schemas import (
    ApiResponse,
    DocumentData,
    UploadData,
    public_processing_status,
    public_upload_status,
)
from verigence.di.application.intake import intake_document
from verigence.di.auth.service_integration import (
    ServiceIntegrationPrincipal,
    require_service_integration,
)
from verigence.di.domain.enums import UploadStatus
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.audit_storage_contexts import (
    AuditStorageContextConflict,
    ensure_audit_storage_context,
    get_audit_storage_context_by_ref,
)
from verigence.di.repositories.database import get_db_session, set_tenant_context, tenant_session
from verigence.di.repositories.documents import get_document
from verigence.di.repositories.subjects import subject_exists
from verigence.di.repositories.tenants import provision_actor
from verigence.di.storage.adapter import get_storage_adapter
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


def _context_uuid(context: dict[str, object], key: str) -> UUID:
    value = context.get(key)
    if not isinstance(value, UUID):
        raise RuntimeError(f"Persisted Audit storage context has invalid {key}")
    return value


def _document_data(doc: dict) -> DocumentData:  # type: ignore[type-arg]
    public_upload = public_upload_status(doc["upload_status"])
    rejected = public_upload == "REJECTED"
    return DocumentData(
        documentId=doc["document_id"],
        documentTypeKey=doc.get("document_type_key"),
        uploadStatus=public_upload,
        processingStatus=public_processing_status(doc.get("processing_status"), rejected),
        confirmationStatus=doc.get("confirmation_status"),
        confidenceScore=doc.get("confidence_score"),
        registeredAtUtc=doc["registered_at_utc"],
    )


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

    project_slug, dealer_slug, outlet_slug, customer_slug = frozen_audit_slugs(
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
            project_slug=project_slug,
            dealer_slug=dealer_slug,
            dealer_outlet_slug=outlet_slug,
            customer_slug=customer_slug,
        )
        await session.commit()
    except AuditStorageContextConflict as exc:
        raise http_exception(ErrorCode.CONFLICT, detail=str(exc)) from exc

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=AuditStorageContextData(
            storageContextId=_context_uuid(context, "storage_context_id"),
            externalContextRef=str(context["external_context_ref"]),
            subjectId=_context_uuid(context, "subject_id"),
            dealerId=_context_uuid(context, "dealer_id"),
            dealerOutletId=_context_uuid(context, "dealer_outlet_id"),
            customerId=_context_uuid(context, "customer_id"),
        ),
    )


@router.post(
    "/audit-storage-contexts/{externalContextRef}/documents",
    response_model=ApiResponse[UploadData],
    status_code=status.HTTP_201_CREATED,
    summary="Upload Audit Core evidence using the frozen storage context",
    operation_id="uploadAuditContextDocument",
)
async def upload_audit_context_document(
    tenantId: str,
    externalContextRef: str,
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
    file: UploadFile = File(..., description="Raw evidence content"),
    documentTypeKey: str | None = Form(None),
) -> ApiResponse[UploadData]:
    external_ref = externalContextRef.strip()
    if not external_ref:
        raise http_exception(ErrorCode.INVALID_REQUEST, detail="externalContextRef is required.")
    correlation_id = str(
        structlog.contextvars.get_contextvars().get("correlation_id", uuid.uuid4())
    )
    async with tenant_session(tenantId) as session:
        context = await get_audit_storage_context_by_ref(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
        )
        if context is None:
            raise http_exception(
                ErrorCode.CONFLICT,
                detail="Audit storage context must be established before document intake.",
            )
        await provision_actor(
            session,
            tenantId,
            service.service_id,
            actor_type="SERVICE",
        )
        doc = await intake_document(
            session=session,
            storage=get_storage_adapter(),
            tenant_id=tenantId,
            subject_id=_context_uuid(context, "subject_id"),
            uploaded_by_actor_id=service.service_id,
            uploaded_by_actor_type="SERVICE",
            correlation_id=correlation_id,
            upload=file,
            document_type_key=documentTypeKey,
            audit_storage_context=context,
        )

    internal_upload: UploadStatus = doc["upload_status"]
    public_upload = public_upload_status(internal_upload)
    rejected = public_upload == "REJECTED"
    return ApiResponse(
        errorCode=(
            "000"
            if not rejected
            else _upload_error_code(internal_upload, doc.get("upload_issue_code"))
        ),
        errorMessage=("File Uploaded Successfully" if not rejected else "Document intake rejected"),
        data=UploadData(
            documentId=doc["document_id"],
            uploadStatus=public_upload,
            processingStatus=public_processing_status(doc.get("processing_status"), rejected),
        ),
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/documents/{documentId}",
    response_model=ApiResponse[DocumentData],
    summary="Get an Audit Core evidence document by frozen context",
    operation_id="getAuditContextDocument",
)
async def get_audit_context_document(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> ApiResponse[DocumentData]:
    del service
    external_ref = externalContextRef.strip()
    async with tenant_session(tenantId) as session:
        context = await get_audit_storage_context_by_ref(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
        )
        if context is None:
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
        doc = await get_document(
            session,
            tenant_id=tenantId,
            document_id=documentId,
            subject_id=_context_uuid(context, "subject_id"),
        )
        if doc is None:
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
        storage_context_id = (
            await session.execute(
                text("""
                    SELECT audit_storage_context_id
                    FROM docintel.documents
                    WHERE tenant_id=:tenant_id AND document_id=:document_id
                """),
                {"tenant_id": tenantId, "document_id": documentId},
            )
        ).scalar_one_or_none()
        if storage_context_id != _context_uuid(context, "storage_context_id"):
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_document_data(doc))


def _upload_error_code(upload_status: UploadStatus, issue_code: object) -> str:
    if upload_status == UploadStatus.UPLOAD_FAILED:
        if issue_code == "FILE_TOO_LARGE":
            return "E007"
        if issue_code == "MIME_TYPE_NOT_ALLOWED":
            return "E006"
        return "E003"
    if upload_status == UploadStatus.CORRUPT:
        return "E002"
    return "E001"

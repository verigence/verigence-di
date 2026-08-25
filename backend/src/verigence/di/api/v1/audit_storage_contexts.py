"""UC02 trusted Audit Core storage-context and document-intake API."""
from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from fastapi.responses import StreamingResponse
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
from verigence.di.storage.adapter import StorageAdapter, get_storage_adapter
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


def _document_content_response(
    *,
    storage: StorageAdapter,
    logical_key: str,
    mime_type: str | None,
    content_hash_sha256: object,
    document_id: UUID,
) -> StreamingResponse:
    """Stream stored document bytes without buffering the full object in DI memory."""
    raw_key = str(logical_key or "")
    filename = raw_key.split("/")[-1] if raw_key else str(document_id)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if content_hash_sha256:
        headers["X-Content-SHA256"] = str(content_hash_sha256)
    return StreamingResponse(
        content=storage.get_stream(logical_key),
        media_type=mime_type or "application/octet-stream",
        headers=headers,
    )


async def _context_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_context_ref: str,
    document_id: UUID,
) -> tuple[dict[str, object], dict]:  # type: ignore[type-arg]
    context = await get_audit_storage_context_by_ref(
        session,
        tenant_id=tenant_id,
        external_context_ref=external_context_ref,
    )
    if context is None:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    doc = await get_document(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
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
            {"tenant_id": tenant_id, "document_id": document_id},
        )
    ).scalar_one_or_none()
    if storage_context_id != _context_uuid(context, "storage_context_id"):
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    return context, doc


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
        _, doc = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_document_data(doc))


@router.get(
    "/audit-storage-contexts/{externalContextRef}/documents/{documentId}/fields",
    summary="Get trusted Audit Core evidence fields",
    operation_id="getAuditContextDocumentFields",
)
async def get_audit_context_document_fields(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> ApiResponse[dict]:  # type: ignore[type-arg]
    del service
    external_ref = externalContextRef.strip()
    async with tenant_session(tenantId) as session:
        _, doc = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
        if doc.get("confirmation_status") != "CONFIRMED":
            return ApiResponse(
                errorCode="E008",
                errorMessage="Document is not yet confirmed — fields not available",
                data=None,
            )
        rows = (
            await session.execute(
                text("""
                    SELECT dfv.canonical_field_id, cf.field_key,
                           dfv.current_value, dfv.value_source,
                           dfv.confidence_score, dfv.version_no, dfv.accepted_at_utc,
                           source_fact.page_no, source_fact.evidence_region
                    FROM docintel.document_field_values dfv
                    JOIN docintel.canonical_fields cf
                      ON cf.canonical_field_id=dfv.canonical_field_id
                    LEFT JOIN LATERAL (
                        SELECT ef.page_no, ef.evidence_region
                        FROM docintel.extracted_facts ef
                        WHERE ef.tenant_id=dfv.tenant_id
                          AND ef.document_id=dfv.document_id
                          AND ef.canonical_field_id=dfv.canonical_field_id
                          AND ef.found_status='FOUND'
                        ORDER BY ef.created_at_utc DESC, ef.extracted_fact_id DESC
                        LIMIT 1
                    ) source_fact ON true
                    WHERE dfv.tenant_id=:tenant_id AND dfv.document_id=:document_id
                      AND dfv.is_current=true
                    ORDER BY cf.field_key
                """),
                {"tenant_id": tenantId, "document_id": documentId},
            )
        ).mappings().all()

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data={
            "documentId": str(documentId),
            "fields": [
                {
                    "canonicalFieldId": str(row["canonical_field_id"]),
                    "fieldKey": row["field_key"],
                    "currentValue": row["current_value"],
                    "valueSource": row["value_source"],
                    "confidenceScore": (
                        float(row["confidence_score"])
                        if row.get("confidence_score") is not None
                        else None
                    ),
                    "versionNo": row["version_no"],
                    "acceptedAt": (
                        row["accepted_at_utc"].isoformat()
                        if row.get("accepted_at_utc")
                        else None
                    ),
                    "pageNo": row.get("page_no"),
                    "evidenceRegion": row.get("evidence_region"),
                }
                for row in rows
            ],
        },
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/documents/{documentId}/content",
    summary="Get trusted Audit Core evidence content",
    operation_id="getAuditContextDocumentContent",
)
async def get_audit_context_document_content(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> Response:
    del service
    external_ref = externalContextRef.strip()
    async with tenant_session(tenantId) as session:
        context, _ = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
        art_row = (
            await session.execute(
                text("""
                    SELECT da.logical_object_key, da.mime_type, d.content_hash_sha256,
                           d.content_state
                    FROM docintel.document_artifacts da
                    JOIN docintel.documents d
                      ON d.tenant_id=da.tenant_id AND d.document_id=da.document_id
                    WHERE da.tenant_id=:tenant_id AND da.document_id=:document_id
                      AND da.artifact_type='ORIGINAL'
                      AND d.audit_storage_context_id=:storage_context_id
                    LIMIT 1
                """),
                {
                    "tenant_id": tenantId,
                    "document_id": documentId,
                    "storage_context_id": _context_uuid(context, "storage_context_id"),
                },
            )
        ).one_or_none()
    if art_row is None:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    if art_row[3] == "PURGED":
        raise http_exception(ErrorCode.DOCUMENT_CONTENT_PURGED)

    return _document_content_response(
        storage=get_storage_adapter(),
        logical_key=str(art_row[0]),
        mime_type=art_row[1],
        content_hash_sha256=art_row[2],
        document_id=documentId,
    )


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

"""UC03 direct Process Consultant Booking document API.

These routes deliberately use the global Security human identity token plus a live
Security authorization decision. They reuse the existing Audit Storage Context so
the Project/Dealer/Outlet/Customer R2 hierarchy is unchanged.

For PC Review, DI remains the authority for extracted facts and authorization, but
large original-document bytes can be read directly from object storage through a
short-lived signed URL. This avoids proxying PDFs/images through the DI Railway
service while keeping the R2 bucket private.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v1.audit_storage_contexts import (
    _context_document,
    _context_uuid,
    _document_content_response,
)
from verigence.di.api.v1.schemas import (
    ApiResponse,
    public_processing_status,
    public_upload_status,
)
from verigence.di.application.intake import intake_document
from verigence.di.auth.human_authorization import (
    HumanTenantAuthorization,
    require_live_tenant_permission,
)
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.audit_storage_contexts import get_audit_storage_context_by_ref
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.tenants import provision_actor
from verigence.di.storage.adapter import StorageAdapter, get_storage_adapter

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["PC Booking Documents"])
logger = structlog.get_logger(__name__)

PC_BOOKING_CONTENT_URL_TTL_SECONDS = 30 * 60


class PcBookingContentAccess(BaseModel):
    documentId: UUID
    contentUrl: str
    contentUrlExpiresAtUtc: datetime
    mimeType: str | None = None


class PcBookingUploadData(BaseModel):
    documentId: UUID
    uploadStatus: str
    processingStatus: str | None = None
    contentUrl: str | None = None
    contentUrlExpiresAtUtc: datetime | None = None
    mimeType: str | None = None


class PcBookingDocumentStatus(BaseModel):
    documentId: UUID
    requirementRef: str
    documentTypeKey: str | None
    uploadStatus: str
    processingStatus: str | None
    registeredAtUtc: str
    contentUrl: str | None = None
    contentUrlExpiresAtUtc: datetime | None = None
    mimeType: str | None = None


class PcBookingDocumentList(BaseModel):
    externalContextRef: str
    documents: list[PcBookingDocumentStatus]


class PcBookingExtractionField(BaseModel):
    sourceFactRef: UUID
    sourceFactVersion: int = 1
    fieldKey: str
    foundStatus: str
    rawValue: str | None = None
    normalizedValue: object | None = None
    confidenceScore: float | None = None
    pageNo: int | None = None
    evidenceRegion: object | None = None


class PcBookingExtractionReview(BaseModel):
    documentId: UUID
    processingStatus: str
    facts: list[PcBookingExtractionField]


def _accepted_upload(doc: dict) -> tuple[str, bool]:  # type: ignore[type-arg]
    public_upload = public_upload_status(doc["upload_status"])
    return public_upload, public_upload == "REJECTED"


async def _original_artifact(
    session: AsyncSession,
    *,
    tenant_id: str,
    storage_context_id: UUID,
    document_id: UUID,
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT da.logical_object_key, da.mime_type, d.content_hash_sha256,
                       d.content_state
                FROM docintel.document_artifacts da
                JOIN docintel.documents d
                  ON d.tenant_id = da.tenant_id AND d.document_id = da.document_id
                WHERE da.tenant_id = :tenant_id
                  AND da.document_id = :document_id
                  AND da.artifact_type = 'ORIGINAL'
                  AND d.audit_storage_context_id = :storage_context_id
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "storage_context_id": storage_context_id,
            },
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def _signed_content_access(
    *,
    storage: StorageAdapter,
    document_id: UUID,
    artifact: dict[str, Any],
) -> PcBookingContentAccess:
    if artifact.get("content_state") == "PURGED":
        raise http_exception(ErrorCode.DOCUMENT_CONTENT_PURGED)
    logical_key = str(artifact.get("logical_object_key") or "")
    if not logical_key:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    expires_at = datetime.now(UTC) + timedelta(seconds=PC_BOOKING_CONTENT_URL_TTL_SECONDS)
    url = await storage.get_presigned_url(logical_key, PC_BOOKING_CONTENT_URL_TTL_SECONDS)
    return PcBookingContentAccess(
        documentId=document_id,
        contentUrl=url,
        contentUrlExpiresAtUtc=expires_at,
        mimeType=artifact.get("mime_type"),
    )


@router.post(
    "/audit-storage-contexts/{externalContextRef}/pc-booking-documents",
    response_model=ApiResponse[PcBookingUploadData],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PC Booking document directly to DI",
    operation_id="uploadPcBookingDocument",
)
async def upload_pc_booking_document(
    tenantId: str,
    externalContextRef: str,
    authorization: Annotated[
        HumanTenantAuthorization,
        Depends(require_live_tenant_permission("di.document.upload")),
    ],
    file: UploadFile = File(..., description="Raw Booking evidence content"),
    documentTypeKey: str | None = Form(None),
    requirementRef: str = Form(..., min_length=1, max_length=160),
) -> ApiResponse[PcBookingUploadData]:
    external_ref = externalContextRef.strip()
    requirement_ref = requirementRef.strip()
    if not external_ref or not requirement_ref:
        raise http_exception(ErrorCode.INVALID_REQUEST, detail="Context and requirementRef are required.")

    correlation_id = str(
        structlog.contextvars.get_contextvars().get("correlation_id", uuid.uuid4())
    )
    storage = get_storage_adapter()
    access: PcBookingContentAccess | None = None
    async with tenant_session(tenantId) as session:
        context = await get_audit_storage_context_by_ref(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
        )
        if context is None:
            raise http_exception(
                ErrorCode.CONFLICT,
                detail="Audit storage context must be established before Booking document intake.",
            )
        await provision_actor(session, tenantId, authorization.user_id, actor_type="USER")
        doc = await intake_document(
            session=session,
            storage=storage,
            tenant_id=tenantId,
            subject_id=_context_uuid(context, "subject_id"),
            uploaded_by_actor_id=authorization.user_id,
            uploaded_by_actor_type="USER",
            correlation_id=correlation_id,
            upload=file,
            document_type_key=documentTypeKey,
            audit_storage_context=context,
            audit_requirement_ref=requirement_ref,
        )
        public_upload, rejected = _accepted_upload(doc)
        if not rejected:
            artifact = await _original_artifact(
                session,
                tenant_id=tenantId,
                storage_context_id=_context_uuid(context, "storage_context_id"),
                document_id=doc["document_id"],
            )
            if artifact is not None:
                try:
                    access = await _signed_content_access(
                        storage=storage,
                        document_id=doc["document_id"],
                        artifact=artifact,
                    )
                except Exception as exc:  # URL generation must never invalidate a successful upload.
                    logger.warning(
                        "pc_booking_content_url_not_generated_after_upload",
                        tenant_id=tenantId,
                        document_id=str(doc["document_id"]),
                        error=str(exc),
                    )

    public_upload, rejected = _accepted_upload(doc)
    return ApiResponse(
        errorCode="000" if not rejected else "E005",
        errorMessage="File Uploaded Successfully" if not rejected else "Document intake rejected",
        data=PcBookingUploadData(
            documentId=doc["document_id"],
            uploadStatus=public_upload,
            processingStatus=public_processing_status(doc.get("processing_status"), rejected),
            contentUrl=access.contentUrl if access else None,
            contentUrlExpiresAtUtc=access.contentUrlExpiresAtUtc if access else None,
            mimeType=access.mimeType if access else None,
        ),
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/pc-booking-documents",
    response_model=ApiResponse[PcBookingDocumentList],
    summary="List PC Booking documents for one Audit storage context",
    operation_id="listPcBookingDocuments",
)
async def list_pc_booking_documents(
    tenantId: str,
    externalContextRef: str,
    authorization: Annotated[
        HumanTenantAuthorization,
        Depends(require_live_tenant_permission("di.document.read")),
    ],
) -> ApiResponse[PcBookingDocumentList]:
    """Return every linked Booking document, not one row per requirement.

    Requirement cardinality is an Audit Core business concern. DI deliberately
    returns every document in the established context so repeatable evidence such
    as Booking payment receipts is not collapsed or superseded here. Each current
    object also gets a fresh short-lived direct-storage URL when possible.
    """
    del authorization
    external_ref = externalContextRef.strip()
    storage = get_storage_adapter()
    async with tenant_session(tenantId) as session:
        context = await get_audit_storage_context_by_ref(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
        )
        if context is None:
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
        rows = (
            await session.execute(
                text(
                    """
                    SELECT d.document_id,
                           d.audit_requirement_ref,
                           COALESCE(dt.document_type_key, d.document_type_hint_key) AS document_type_key,
                           d.upload_status,
                           d.processing_status,
                           d.registered_at_utc,
                           d.content_state,
                           da.logical_object_key,
                           da.mime_type
                    FROM docintel.documents d
                    LEFT JOIN docintel.document_types dt
                      ON dt.document_type_id = d.document_type_id
                    LEFT JOIN docintel.document_artifacts da
                      ON da.tenant_id = d.tenant_id
                     AND da.document_id = d.document_id
                     AND da.artifact_type = 'ORIGINAL'
                    WHERE d.tenant_id = :tenant_id
                      AND d.audit_storage_context_id = :storage_context_id
                      AND d.audit_requirement_ref IS NOT NULL
                    ORDER BY d.registered_at_utc ASC,
                             d.document_id ASC
                    """
                ),
                {
                    "tenant_id": tenantId,
                    "storage_context_id": _context_uuid(context, "storage_context_id"),
                },
            )
        ).mappings().all()

    documents: list[PcBookingDocumentStatus] = []
    for row in rows:
        upload_status = public_upload_status(row["upload_status"])
        rejected = upload_status == "REJECTED"
        access: PcBookingContentAccess | None = None
        if not rejected and row.get("logical_object_key") and row.get("content_state") != "PURGED":
            try:
                access = await _signed_content_access(
                    storage=storage,
                    document_id=row["document_id"],
                    artifact={
                        "logical_object_key": row["logical_object_key"],
                        "mime_type": row["mime_type"],
                        "content_state": row["content_state"],
                    },
                )
            except Exception as exc:
                logger.warning(
                    "pc_booking_content_url_not_generated_for_list",
                    tenant_id=tenantId,
                    document_id=str(row["document_id"]),
                    error=str(exc),
                )
        documents.append(
            PcBookingDocumentStatus(
                documentId=row["document_id"],
                requirementRef=str(row["audit_requirement_ref"]),
                documentTypeKey=row["document_type_key"],
                uploadStatus=upload_status,
                processingStatus=public_processing_status(row["processing_status"], rejected),
                registeredAtUtc=row["registered_at_utc"].isoformat(),
                contentUrl=access.contentUrl if access else None,
                contentUrlExpiresAtUtc=access.contentUrlExpiresAtUtc if access else None,
                mimeType=access.mimeType if access else row.get("mime_type"),
            )
        )
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=PcBookingDocumentList(externalContextRef=external_ref, documents=documents),
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/pc-booking-documents/{documentId}/extraction-review",
    response_model=ApiResponse[PcBookingExtractionReview],
    summary="Read immutable machine extraction for PC Booking review",
    operation_id="getPcBookingExtractionReview",
)
async def get_pc_booking_extraction_review(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    authorization: Annotated[
        HumanTenantAuthorization,
        Depends(require_live_tenant_permission("di.document.fields.read")),
    ],
) -> ApiResponse[PcBookingExtractionReview]:
    del authorization
    external_ref = externalContextRef.strip()
    rows: Sequence[Any] = []
    async with tenant_session(tenantId) as session:
        _, doc = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
        current_run_id = doc.get("current_processing_run_id")
        if current_run_id is not None:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT ef.extracted_fact_id, cf.field_key, ef.found_status,
                               ef.raw_value_text, ef.normalized_value,
                               ef.confidence_score, ef.page_no, ef.evidence_region
                        FROM docintel.extracted_facts ef
                        JOIN docintel.canonical_fields cf
                          ON cf.canonical_field_id = ef.canonical_field_id
                        WHERE ef.tenant_id = :tenant_id
                          AND ef.document_id = :document_id
                          AND ef.processing_run_id = :processing_run_id
                        ORDER BY cf.field_key, ef.created_at_utc, ef.extracted_fact_id
                        """
                    ),
                    {
                        "tenant_id": tenantId,
                        "document_id": documentId,
                        "processing_run_id": current_run_id,
                    },
                )
            ).mappings().all()

    facts = [
        PcBookingExtractionField(
            sourceFactRef=row["extracted_fact_id"],
            sourceFactVersion=1,
            fieldKey=row["field_key"],
            foundStatus=row["found_status"],
            rawValue=row["raw_value_text"],
            normalizedValue=row["normalized_value"],
            confidenceScore=(
                float(row["confidence_score"])
                if row["confidence_score"] is not None
                else None
            ),
            pageNo=row["page_no"],
            evidenceRegion=row["evidence_region"],
        )
        for row in rows
    ]
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=PcBookingExtractionReview(
            documentId=documentId,
            processingStatus=public_processing_status(doc.get("processing_status"), False),
            facts=facts,
        ),
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/pc-booking-documents/{documentId}/content-url",
    response_model=ApiResponse[PcBookingContentAccess],
    summary="Mint a short-lived direct R2/MinIO URL for the original Booking document",
    operation_id="getPcBookingDocumentContentUrl",
)
async def get_pc_booking_document_content_url(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    authorization: Annotated[
        HumanTenantAuthorization,
        Depends(require_live_tenant_permission("di.document.content.read")),
    ],
) -> ApiResponse[PcBookingContentAccess]:
    del authorization
    external_ref = externalContextRef.strip()
    async with tenant_session(tenantId) as session:
        context, _ = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
        artifact = await _original_artifact(
            session,
            tenant_id=tenantId,
            storage_context_id=_context_uuid(context, "storage_context_id"),
            document_id=documentId,
        )
    if artifact is None:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    access = await _signed_content_access(
        storage=get_storage_adapter(),
        document_id=documentId,
        artifact=artifact,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=access)


@router.get(
    "/audit-storage-contexts/{externalContextRef}/pc-booking-documents/{documentId}/content",
    summary="Stream the original PC Booking document",
    operation_id="getPcBookingDocumentContent",
)
async def get_pc_booking_document_content(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    authorization: Annotated[
        HumanTenantAuthorization,
        Depends(require_live_tenant_permission("di.document.content.read")),
    ],
) -> Response:
    """Backward-compatible DI proxy path; Review now prefers content-url."""
    del authorization
    external_ref = externalContextRef.strip()
    async with tenant_session(tenantId) as session:
        context, _ = await _context_document(
            session,
            tenant_id=tenantId,
            external_context_ref=external_ref,
            document_id=documentId,
        )
        artifact = await _original_artifact(
            session,
            tenant_id=tenantId,
            storage_context_id=_context_uuid(context, "storage_context_id"),
            document_id=documentId,
        )
    if artifact is None:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    if artifact.get("content_state") == "PURGED":
        raise http_exception(ErrorCode.DOCUMENT_CONTENT_PURGED)
    return _document_content_response(
        storage=get_storage_adapter(),
        logical_key=str(artifact["logical_object_key"]),
        mime_type=artifact.get("mime_type"),
        content_hash_sha256=artifact.get("content_hash_sha256"),
        document_id=documentId,
    )

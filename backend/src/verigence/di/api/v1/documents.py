"""api/v1/documents.py — Subject Document REST endpoints.

Implements:
  POST  /v1/tenants/{tenantId}/subjects/{subjectId}/documents   uploadSubjectDocument
  GET   /v1/tenants/{tenantId}/subjects/{subjectId}/documents   getSubjectDocuments
  GET   /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}  getSubjectDocument
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from verigence.di.api.v1.schemas import (
    DocumentResponse,
    SubjectDocumentView,
)
from verigence.di.application.intake import intake_document
from verigence.di.auth.dependencies import require_tenant_actor
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import SourceChannel
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.documents import (
    get_document,
    list_subject_documents,
)
from verigence.di.repositories.subjects import subject_exists
from verigence.di.storage.adapter import get_storage_adapter

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["Subject Documents"])


def _doc_response(doc: dict) -> DocumentResponse:  # type: ignore[type-arg]
    return DocumentResponse(
        tenantId=doc["tenant_id"],
        documentId=doc["document_id"],
        subjectId=doc.get("subject_id"),
        sourceChannel=doc["source_channel"],
        uploadStatus=doc["upload_status"],
        processingStatus=doc["processing_status"],
        confirmationStatus=doc["confirmation_status"],
        confidenceScore=doc.get("confidence_score"),
        verificationThresholdApplied=doc.get("verification_threshold_applied"),
        humanVerificationStatus=doc.get("human_verification_status"),
        verificationState=doc["verification_state"],
        contentState=doc["content_state"],
        originalFilename=doc.get("original_filename"),
        declaredMimeType=doc.get("declared_mime_type"),
        detectedMimeType=doc.get("detected_mime_type"),
        fileSizeBytes=doc.get("file_size_bytes"),
        contentHashSha256=doc.get("content_hash_sha256"),
        pageCount=doc.get("page_count"),
        correlationId=doc["correlation_id"],
        registeredAtUtc=doc["registered_at_utc"],
        processedAtUtc=doc.get("processed_at_utc"),
        confirmedAtUtc=doc.get("confirmed_at_utc"),
        uploadIssueCode=doc.get("upload_issue_code"),
        uploadIssueDetail=doc.get("upload_issue_detail"),
        processingFailureCode=doc.get("processing_failure_code"),
        duplicateOfDocumentId=doc.get("duplicate_of_document_id"),
        replacesDocumentId=doc.get("replaces_document_id"),
    )


@router.post(
    "/subjects/{subjectId}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one logical document for a Subject",
    operation_id="uploadSubjectDocument",
)
async def upload_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_actor)],
    file: UploadFile = File(..., description="Raw binary content"),
    sourceChannel: str = Form(...),
    documentTypeKey: str | None = Form(None),
    capturedAt: str | None = Form(None),
    sourceReference: str | None = Form(None),
    replacesDocumentId: str | None = Form(None),
) -> DocumentResponse:
    # Validate sourceChannel
    try:
        channel = SourceChannel(sourceChannel)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "VALIDATION_ERROR",
                "title": f"Invalid sourceChannel: {sourceChannel!r}. Must be MOBILE, WEB, or API.",
            },
        ) from exc
    if channel == SourceChannel.WHATSAPP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "VALIDATION_ERROR", "title": "WHATSAPP channel not accepted here"},
        )

    if not actor.is_uploader:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"type": "FORBIDDEN", "title": "Uploader role required"},
        )

    replaces_id: uuid.UUID | None = None
    if replacesDocumentId:
        try:
            replaces_id = uuid.UUID(replacesDocumentId)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"type": "VALIDATION_ERROR", "title": "Invalid replacesDocumentId UUID"},
            ) from exc

    from datetime import datetime
    captured_at_dt: datetime | None = None
    if capturedAt:
        try:
            captured_at_dt = datetime.fromisoformat(capturedAt)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"type": "VALIDATION_ERROR", "title": "Invalid capturedAt datetime format"},
            ) from exc

    # Get correlation_id from request state (set by middleware)
    import structlog
    ctx = structlog.contextvars.get_contextvars()
    correlation_id: str = ctx.get("correlation_id", str(uuid.uuid4()))

    storage = get_storage_adapter()

    async with tenant_session(actor.tenant_id) as session:
        # Validate subject exists and belongs to this tenant
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"type": "NOT_FOUND", "title": "Subject not found or inactive"},
            )

        try:
            doc = await intake_document(
                session=session,
                storage=storage,
                tenant_id=actor.tenant_id,
                subject_id=subjectId,
                source_channel=channel,
                uploaded_by_actor_id=actor.actor_id,
                uploaded_by_actor_type=actor.actor_type.value,
                correlation_id=correlation_id,
                upload=file,
                document_type_key=documentTypeKey,
                captured_at=captured_at_dt,
                source_reference=sourceReference,
                replaces_document_id=replaces_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"type": "INTAKE_ERROR", "title": str(exc)},
            ) from exc

    return _doc_response(doc)


@router.get(
    "/subjects/{subjectId}/documents",
    response_model=SubjectDocumentView,
    summary="Get the full requirement and document state for a Subject",
    operation_id="getSubjectDocuments",
)
async def get_subject_documents(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_actor)],
) -> SubjectDocumentView:
    async with tenant_session(actor.tenant_id) as session:
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"type": "NOT_FOUND", "title": "Subject not found"},
            )
        docs = await list_subject_documents(
            session, tenant_id=actor.tenant_id, subject_id=subjectId
        )

    return SubjectDocumentView(
        tenantId=actor.tenant_id,
        subjectId=subjectId,
        configurationStatus="REQUIREMENT_PROFILE_NOT_ASSIGNED",
        documents=[_doc_response(d) for d in docs],
        totalDocuments=len(docs),
    )


@router.get(
    "/subjects/{subjectId}/documents/{documentId}",
    response_model=DocumentResponse,
    summary="Get one actual document within the Tenant + Subject boundary",
    operation_id="getSubjectDocument",
)
async def get_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_actor)],
) -> DocumentResponse:
    async with tenant_session(actor.tenant_id) as session:
        doc = await get_document(
            session,
            tenant_id=actor.tenant_id,
            document_id=documentId,
            subject_id=subjectId,
        )

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "NOT_FOUND", "title": "Document not found"},
        )

    return _doc_response(doc)

"""api/v1/documents.py — Subject Document REST endpoints.

Implements:
  POST  /v1/tenants/{tenantId}/subjects/{subjectId}/documents   uploadSubjectDocument
  GET   /v1/tenants/{tenantId}/subjects/{subjectId}/documents   getSubjectDocuments
  GET   /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}  getSubjectDocument

v2.2: authorization uses require_tenant_permission() (permissions[], not role names).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import text

from verigence.di.api.v1.schemas import (
    DocumentResponse,
    SubjectDocumentView,
)
from verigence.di.application.intake import intake_document
from verigence.di.auth.dependencies import require_tenant_actor, require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ProcessingStatus, SourceChannel, UploadStatus
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.documents import (
    delete_document,
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
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.DOCUMENT_UPLOAD))],
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
        raise problem(
            400,
            f"Invalid sourceChannel: {sourceChannel!r}. Must be MOBILE, WEB, or API.",
            ErrorCode.INVALID_REQUEST,
        ) from exc
    if channel == SourceChannel.WHATSAPP:
        raise problem(400, "WHATSAPP channel not accepted on this endpoint",
                      ErrorCode.INVALID_REQUEST)

    replaces_id: uuid.UUID | None = None
    if replacesDocumentId:
        try:
            replaces_id = uuid.UUID(replacesDocumentId)
        except ValueError as exc:
            raise problem(400, "Invalid replacesDocumentId: not a valid UUID",
                          ErrorCode.INVALID_REQUEST) from exc

    captured_at_dt: datetime | None = None
    if capturedAt:
        try:
            captured_at_dt = datetime.fromisoformat(capturedAt)
        except ValueError as exc:
            raise problem(400, "Invalid capturedAt: must be ISO 8601 datetime",
                          ErrorCode.INVALID_REQUEST) from exc

    # Get correlation_id from request state (set by middleware)
    ctx = structlog.contextvars.get_contextvars()
    correlation_id: str = ctx.get("correlation_id", str(uuid.uuid4()))

    storage = get_storage_adapter()

    async with tenant_session(actor.tenant_id) as session:
        # Validate subject exists and belongs to this tenant
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise problem(404, "Subject not found or inactive", ErrorCode.SUBJECT_NOT_FOUND)

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
            raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)
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
        raise problem(404, "Document not found", ErrorCode.SUBJECT_DOCUMENT_NOT_FOUND)

    return _doc_response(doc)


@router.delete(
    "/subjects/{subjectId}/documents/{documentId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete an eligible document and all its data",
    operation_id="deleteSubjectDocument",
)
async def delete_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_DELETE)),
) -> None:
    """Hard-delete a document.

    Eligible when:
      1. upload_status IN (NOT_FIT, CORRUPT, UPLOAD_FAILED)
      2. upload_status = FIT AND processing_status IN (PENDING, FAILED)

    audit_events are preserved. All other child rows + object storage bytes
    are permanently removed.
    """
    storage = get_storage_adapter()

    async with tenant_session(actor.tenant_id) as session:
        doc = await get_document(
            session,
            tenant_id=actor.tenant_id,
            document_id=documentId,
            subject_id=subjectId,
        )
        if doc is None:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)

        upload_status = doc["upload_status"]
        processing_status = doc["processing_status"]

        eligible = (
            upload_status in (
                UploadStatus.NOT_FIT,
                UploadStatus.CORRUPT,
                UploadStatus.UPLOAD_FAILED,
            )
            or (
                upload_status == UploadStatus.FIT
                and processing_status in (
                    ProcessingStatus.NOT_STARTED,
                    ProcessingStatus.FAILED,
                )
            )
        )
        if not eligible:
            raise problem(
                409,
                f"Document cannot be deleted in state upload={upload_status.value} "
                f"processing={processing_status.value}",
                ErrorCode.DOCUMENT_NOT_ELIGIBLE_FOR_DELETE,
            )

        await delete_document(
            session,
            tenant_id=actor.tenant_id,
            document_id=documentId,
            subject_id=subjectId,
            storage=storage,
        )
        await session.commit()


# ── Extensions: getSubjectDocumentContent, getSubjectDocumentFields,
#                getSubjectDocumentExceptions, getSubjectDocumentQuality ────────


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/content",
    operation_id="getSubjectDocumentContent",
    summary="Stream original document bytes",
)
async def get_subject_document_content(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_CONTENT_READ)),
) -> Response:
    """Return original document bytes (OAS: getSubjectDocumentContent)."""
    async with tenant_session(actor.tenant_id) as session:
        art_row = (
            await session.execute(
                text("""
                    SELECT da.logical_object_key, da.mime_type, d.content_hash_sha256,
                           d.content_state
                    FROM docintel.document_artifacts da
                    JOIN docintel.documents d ON d.tenant_id=da.tenant_id
                      AND d.document_id=da.document_id
                    WHERE da.tenant_id=:tid AND da.document_id=:doc_id
                      AND da.artifact_type='ORIGINAL'
                      AND d.subject_id=:sid
                    LIMIT 1
                """),
                {"tid": str(actor.tenant_id), "doc_id": documentId, "sid": subjectId},
            )
        ).one_or_none()
    if not art_row:
        raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)
    if art_row[3] == "PURGED":
        raise problem(410, "Document content purged", ErrorCode.DOCUMENT_CONTENT_PURGED)

    storage = get_storage_adapter()
    chunks = []
    async for chunk in await storage.get_stream(art_row[0]):
        chunks.append(chunk)
    data = b"".join(chunks)

    # Build a safe filename from the R2 key (last path segment) for Content-Disposition
    raw_key: str = art_row[0] or ""
    filename = raw_key.split("/")[-1] if raw_key else f"{documentId}"

    headers: dict[str, str] = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if art_row[2]:
        headers["X-Content-SHA256"] = art_row[2]
    return Response(
        content=data,
        media_type=art_row[1] or "application/octet-stream",
        headers=headers,
    )


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/fields",
    operation_id="getSubjectDocumentFields",
    summary="Return extracted field values for a confirmed document",
)
async def get_subject_document_fields(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_FIELDS_READ)),
) -> dict:  # type: ignore[type-arg]
    """Return extraction result (OAS: getSubjectDocumentFields)."""
    return await _load_document_fields(actor.tenant_id, documentId)


async def _load_document_fields(tenant_id: str, document_id: uuid.UUID) -> dict:  # type: ignore[type-arg]
    """Shared helper: load current accepted field values for a document."""
    async with tenant_session(tenant_id) as session:
        doc_row = (
            await session.execute(
                text("SELECT confirmation_status FROM docintel.documents WHERE tenant_id=:tid AND document_id=:doc_id"),
                {"tid": tenant_id, "doc_id": document_id},
            )
        ).one_or_none()
        if not doc_row:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row[0] != "CONFIRMED":
            raise problem(409, "Document is not yet CONFIRMED", ErrorCode.INVALID_DOCUMENT_STATE)

        rows = (
            await session.execute(
                text("""
                    SELECT dfv.canonical_field_id, cf.field_key,
                           dfv.current_value, dfv.value_source,
                           dfv.confidence_score, dfv.version_no, dfv.accepted_at_utc
                    FROM docintel.document_field_values dfv
                    JOIN docintel.canonical_fields cf ON cf.canonical_field_id=dfv.canonical_field_id
                    WHERE dfv.tenant_id=:tid AND dfv.document_id=:doc_id AND dfv.is_current=true
                    ORDER BY cf.field_key
                """),
                {"tid": tenant_id, "doc_id": document_id},
            )
        ).mappings().all()

    return {
        "documentId": str(document_id),
        "fields": [
            {
                "canonicalFieldId": str(r["canonical_field_id"]),
                "fieldKey": r["field_key"],
                "currentValue": r["current_value"],
                "valueSource": r["value_source"],
                "confidenceScore": float(r["confidence_score"]) if r.get("confidence_score") else None,
                "versionNo": r["version_no"],
                "acceptedAt": r["accepted_at_utc"].isoformat() if r.get("accepted_at_utc") else None,
            }
            for r in rows
        ],
    }


@router.get(
    "/subjects/{subjectId}/document-exceptions",
    operation_id="getSubjectDocumentExceptions",
    summary="List exception documents for a Subject",
)
async def get_subject_document_exceptions(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_READ)),
) -> list:  # type: ignore[type-arg]
    """Return Subject-scoped exceptions (OAS: getSubjectDocumentExceptions)."""
    async with tenant_session(actor.tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT document_id, upload_status, processing_status,
                           upload_issue_code, processing_failure_code, registered_at_utc
                    FROM docintel.documents
                    WHERE tenant_id=:tid AND subject_id=:sid
                      AND (
                          upload_status IN ('NOT_FIT','CORRUPT','UPLOAD_FAILED')
                          OR processing_status IN ('RETRY_PENDING','FAILED')
                      )
                      AND replaced_by_document_id IS NULL
                    ORDER BY registered_at_utc DESC
                """),
                {"tid": str(actor.tenant_id), "sid": subjectId},
            )
        ).mappings().all()
    return [
        {
            "documentId": str(r["document_id"]),
            "uploadStatus": r["upload_status"],
            "processingStatus": r["processing_status"],
            "issueCode": r.get("upload_issue_code") or r.get("processing_failure_code"),
            "registeredAt": r["registered_at_utc"].isoformat() if r.get("registered_at_utc") else None,
        }
        for r in rows
    ]


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/quality",
    operation_id="getSubjectDocumentQuality",
    summary="Return quality rule results for a document",
)
async def get_subject_document_quality(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_READ)),
) -> dict:  # type: ignore[type-arg]
    """Return quality rule results for a document (OAS: getSubjectDocumentQuality)."""
    async with tenant_session(actor.tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT rule_key, outcome, parameters_applied, measurement, message, evaluated_at_utc
                    FROM docintel.document_quality_results
                    WHERE tenant_id=:tid AND document_id=:doc_id
                    ORDER BY evaluated_at_utc DESC
                """),
                {"tid": str(actor.tenant_id), "doc_id": documentId},
            )
        ).mappings().all()
    return {
        "documentId": str(documentId),
        "qualityResults": [
            {
                "ruleKey": r["rule_key"],
                "outcome": r["outcome"],
                "parametersApplied": r["parameters_applied"],
                "measurement": r["measurement"],
                "message": r["message"],
                "evaluatedAt": r["evaluated_at_utc"].isoformat() if r.get("evaluated_at_utc") else None,
            }
            for r in rows
        ],
    }

"""api/v1/documents.py — Subject Document REST endpoints.

D8:  All responses wrapped in ApiResponse envelope (errorCode, errorMessage, data).
D9:  Upload request: file + documentTypeKey only. sourceChannel removed.
D11: GET responses return slim DocumentData only.
D12: New /document-types summary endpoint.
"""
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import text

from verigence.di.api.v1.schemas import (
    ApiResponse,
    DocumentData,
    DocumentListData,
    DocumentTypeCount,
    DocumentTypeSummaryData,
    UploadData,
    public_processing_status,
    public_upload_status,
)
from verigence.di.application.intake import intake_document
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ProcessingStatus, UploadStatus
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.documents import (
    delete_document,
    get_document,
    list_document_type_counts,
    list_subject_documents,
)
from verigence.di.repositories.subjects import subject_exists
from verigence.di.storage.adapter import get_storage_adapter

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["Subject Documents"])

logger = structlog.get_logger(__name__)

_EC_SUCCESS = "000"
_EC_QUALITY_FAILED = "E001"
_EC_CORRUPT = "E002"
_EC_STORAGE_ERROR = "E003"
_EC_SUBJECT_NOT_FOUND = "E004"
_EC_DOCUMENT_NOT_FOUND = "E005"
_EC_UNSUPPORTED_TYPE = "E006"
_EC_FILE_TOO_LARGE = "E007"
_EC_NOT_CONFIRMED = "E008"


def _upload_error_code(internal_status: UploadStatus, issue_code: str | None) -> str:
    """Map internal upload failure to public error code."""
    if internal_status == UploadStatus.UPLOAD_FAILED:
        if issue_code == "FILE_TOO_LARGE":
            return _EC_FILE_TOO_LARGE
        if issue_code == "MIME_TYPE_NOT_ALLOWED":
            return _EC_UNSUPPORTED_TYPE
        return _EC_STORAGE_ERROR
    if internal_status == UploadStatus.CORRUPT:
        return _EC_CORRUPT
    return _EC_QUALITY_FAILED


def _upload_error_message(internal_status: UploadStatus, issue_code: str | None) -> str:
    if internal_status == UploadStatus.UPLOAD_FAILED:
        if issue_code == "FILE_TOO_LARGE":
            return "File exceeds maximum allowed size"
        if issue_code == "MIME_TYPE_NOT_ALLOWED":
            return "File type is not supported"
        return "Storage error — please retry"
    if internal_status == UploadStatus.CORRUPT:
        return "File is corrupt or unreadable"
    return "File did not meet quality requirements"


def _doc_data(doc: dict) -> DocumentData:
    """Build slim public DocumentData from internal doc dict."""
    internal_upload = doc["upload_status"]
    pub_upload = public_upload_status(internal_upload)
    rejected = pub_upload == "REJECTED"
    pub_processing = public_processing_status(doc.get("processing_status"), rejected)
    return DocumentData(
        documentId=doc["document_id"],
        documentTypeKey=doc.get("document_type_key"),
        uploadStatus=pub_upload,
        processingStatus=pub_processing,
        confirmationStatus=doc.get("confirmation_status"),
        confidenceScore=doc.get("confidence_score"),
        registeredAtUtc=doc["registered_at_utc"],
    )


@router.post(
    "/subjects/{subjectId}/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Upload Document",
    description=(
        "Upload a binary document file for a Subject. Runs quality rules; returns ACCEPTED or REJECTED. "
        "Required permission: `di.document.upload`. "
        "Returns D8 envelope: errorCode=000 (ACCEPTED) or E001–E007 (REJECTED) with uploadStatus and documentId."
    ),
    response_description="Upload outcome",
    operation_id="uploadSubjectDocument",
)
async def upload_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.DOCUMENT_UPLOAD))],
    file: UploadFile = File(..., description="Raw binary content"),
    documentTypeKey: str | None = Form(None),
) -> ApiResponse[UploadData]:
    ctx = structlog.contextvars.get_contextvars()
    correlation_id: str = ctx.get("correlation_id", str(uuid.uuid4()))
    storage = get_storage_adapter()

    async with tenant_session(actor.tenant_id) as session:
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise problem(404, "Subject not found or inactive", ErrorCode.SUBJECT_NOT_FOUND)

        doc = await intake_document(
            session=session,
            storage=storage,
            tenant_id=actor.tenant_id,
            subject_id=subjectId,
            uploaded_by_actor_id=actor.actor_id,
            uploaded_by_actor_type=actor.actor_type.value,
            correlation_id=correlation_id,
            upload=file,
            document_type_key=documentTypeKey,
        )

    internal_upload: UploadStatus = doc["upload_status"]
    pub_upload = public_upload_status(internal_upload)
    rejected = pub_upload == "REJECTED"

    if rejected:
        issue_code = doc.get("upload_issue_code")
        return ApiResponse(
            errorCode=_upload_error_code(internal_upload, issue_code),
            errorMessage=_upload_error_message(internal_upload, issue_code),
            data=UploadData(
                documentId=doc["document_id"],
                uploadStatus=pub_upload,
                processingStatus=None,
            ),
        )

    pub_processing = public_processing_status(doc.get("processing_status"), rejected)
    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="File Uploaded Successfully",
        data=UploadData(
            documentId=doc["document_id"],
            uploadStatus=pub_upload,
            processingStatus=pub_processing,
        ),
    )


@router.get(
    "/subjects/{subjectId}/documents",
    summary="List Subject Documents",
    description=(
        "List all documents for a Subject in the Tenant. "
        "Required permission: `di.document.read`. "
        "Returns D8 envelope with documents array and total count."
    ),
    response_description="Document list",
    operation_id="getSubjectDocuments",
)
async def get_subject_documents(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.DOCUMENT_READ))],
) -> ApiResponse[DocumentListData]:
    async with tenant_session(actor.tenant_id) as session:
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)
        docs = await list_subject_documents(
            session, tenant_id=actor.tenant_id, subject_id=subjectId
        )

    doc_list = [_doc_data(d) for d in docs]
    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data=DocumentListData(
            subjectId=subjectId,
            totalDocuments=len(doc_list),
            documents=doc_list,
        ),
    )


@router.get(
    "/subjects/{subjectId}/documents/{documentId}",
    summary="Get Subject Document",
    description=(
        "Fetch a single document record by ID within the Tenant + Subject boundary. "
        "Required permission: `di.document.read`. "
        "Returns D8 envelope with slim DocumentData (status, confidence, timestamps)."
    ),
    response_description="Document record",
    operation_id="getSubjectDocument",
)
async def get_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.DOCUMENT_READ))],
) -> ApiResponse[DocumentData]:
    async with tenant_session(actor.tenant_id) as session:
        doc = await get_document(
            session,
            tenant_id=actor.tenant_id,
            document_id=documentId,
            subject_id=subjectId,
        )

    if doc is None:
        raise problem(404, "Document not found", ErrorCode.SUBJECT_DOCUMENT_NOT_FOUND)

    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data=_doc_data(doc),
    )


@router.get(
    "/subjects/{subjectId}/document-types",
    summary="Get Subject Document Type Summary",
    description=(
        "Return a count of accepted documents per document type for a Subject. "
        "Required permission: `di.document.read`. "
        "Returns D8 envelope with documentTypes array keyed by documentTypeKey."
    ),
    response_description="Document type counts",
    operation_id="getSubjectDocumentTypes",
)
async def get_subject_document_types(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.DOCUMENT_READ))],
) -> ApiResponse[DocumentTypeSummaryData]:
    async with tenant_session(actor.tenant_id) as session:
        exists = await subject_exists(session, tenant_id=actor.tenant_id, subject_id=subjectId)
        if not exists:
            raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)
        counts = await list_document_type_counts(
            session, tenant_id=actor.tenant_id, subject_id=subjectId
        )

    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data=DocumentTypeSummaryData(
            subjectId=subjectId,
            totalDocuments=len(doc_list),
            documents=doc_list,
        ),
    )


@router.delete(
    "/subjects/{subjectId}/documents/{documentId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Subject Document",
    description=(
        "Hard-delete a document and all its associated data (artifacts, field values, quality results). "
        "Only eligible when upload_status is NOT_FIT/CORRUPT/UPLOAD_FAILED, or when FIT + NOT_STARTED/FAILED. "
        "Required permission: `di.document.delete`. "
        "Returns 204 No Content on success, 409 if the document is in a non-deletable state."
    ),
    operation_id="deleteSubjectDocument",
)
async def delete_subject_document(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_DELETE)),
) -> None:
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
        processing_status = doc.get("processing_status")

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
                f"processing={processing_status.value if processing_status else 'N/A'}",
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


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/content",
    operation_id="getSubjectDocumentContent",
    summary="Get Document Content",
    description=(
        "Stream the original document bytes from storage. "
        "Required permission: `di.document.content.read`. "
        "Returns the raw file with Content-Disposition and X-Content-SHA256 headers. "
        "Returns 410 Gone if the document content has been purged by a retention policy."
    ),
)
async def get_subject_document_content(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_CONTENT_READ)),
) -> Response:
    """Return original document bytes."""
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
    async for chunk in storage.get_stream(art_row[0]):
        chunks.append(chunk)
    data = b"".join(chunks)

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
    summary="Get Document Fields",
    description=(
        "Return all current extracted field values for a CONFIRMED document. "
        "Required permission: `di.document.fields.read`. "
        "The existing field contract is preserved and optional pageNo/evidenceRegion "
        "metadata identifies the latest machine source location when available. "
        "Returns errorCode=E008 if the document has not yet been confirmed."
    ),
)
async def get_subject_document_fields(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_FIELDS_READ)),
) -> ApiResponse[dict]:  # type: ignore[type-arg]
    async with tenant_session(actor.tenant_id) as session:
        doc_row = (
            await session.execute(
                text(
                    "SELECT confirmation_status FROM docintel.documents "
                    "WHERE tenant_id=:tid AND document_id=:doc_id"
                ),
                {"tid": actor.tenant_id, "doc_id": documentId},
            )
        ).one_or_none()
        if not doc_row:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row[0] != "CONFIRMED":
            return ApiResponse(
                errorCode=_EC_NOT_CONFIRMED,
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
                    WHERE dfv.tenant_id=:tid AND dfv.document_id=:doc_id
                      AND dfv.is_current=true
                    ORDER BY cf.field_key
                """),
                {"tid": actor.tenant_id, "doc_id": documentId},
            )
        ).mappings().all()

    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data={
            "documentId": str(documentId),
            "fields": [
                {
                    "canonicalFieldId": str(r["canonical_field_id"]),
                    "fieldKey": r["field_key"],
                    "currentValue": r["current_value"],
                    "valueSource": r["value_source"],
                    "confidenceScore": (
                        float(r["confidence_score"])
                        if r.get("confidence_score") is not None
                        else None
                    ),
                    "versionNo": r["version_no"],
                    "acceptedAt": (
                        r["accepted_at_utc"].isoformat()
                        if r.get("accepted_at_utc")
                        else None
                    ),
                    "pageNo": r.get("page_no"),
                    "evidenceRegion": r.get("evidence_region"),
                }
                for r in rows
            ],
        },
    )


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/quality",
    operation_id="getSubjectDocumentQuality",
    summary="Get Document Quality Results",
    description=(
        "Return all quality rule evaluation results for a document. "
        "Required permission: `di.document.read`. "
        "Returns D8 envelope with qualityResults array (ruleKey, outcome, measurement, message)."
    ),
)
async def get_subject_document_quality(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_READ)),
) -> ApiResponse[dict]:  # type: ignore[type-arg]
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

    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data={
            "documentId": str(documentId),
            "qualityResults": [
                {
                    "ruleKey": r["rule_key"],
                    "outcome": r["outcome"],
                    "parametersApplied": r["parameters_applied"],
                    "measurement": r["measurement"],
                    "message": r["message"],
                    "evaluatedAt": (
                        r["evaluated_at_utc"].isoformat()
                        if r.get("evaluated_at_utc")
                        else None
                    ),
                }
                for r in rows
            ],
        },
    )


@router.get(
    "/subjects/{subjectId}/document-exceptions",
    operation_id="getSubjectDocumentExceptions",
    summary="Get Subject Document Exceptions",
    description=(
        "List all exception documents for a Subject — documents in NOT_FIT, CORRUPT, UPLOAD_FAILED, "
        "RETRY_PENDING, or FAILED state. "
        "Required permission: `di.document.read`. "
        "Returns D8 envelope with exception list."
    ),
)
async def get_subject_document_exceptions(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_READ)),
) -> ApiResponse[list]:  # type: ignore[type-arg]
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

    return ApiResponse(
        errorCode=_EC_SUCCESS,
        errorMessage="Success",
        data=[
            {
                "documentId": str(r["document_id"]),
                "uploadStatus": r["upload_status"],
                "processingStatus": r["processing_status"],
                "issueCode": r.get("upload_issue_code") or r.get("processing_failure_code"),
                "registeredAt": (
                    r["registered_at_utc"].isoformat()
                    if r.get("registered_at_utc")
                    else None
                ),
            }
            for r in rows
        ],
    )

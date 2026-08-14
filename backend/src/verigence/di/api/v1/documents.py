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

# ── Error codes (D8) ──────────────────────────────────────────────────────────
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
    return _EC_QUALITY_FAILED   # NOT_FIT


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


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post(
    "/subjects/{subjectId}/documents",
    status_code=status.HTTP_201_CREATED,
    summary="Upload one document for a Subject",
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


# ── Get all documents for a subject ──────────────────────────────────────────

@router.get(
    "/subjects/{subjectId}/documents",
    summary="List all documents for a Subject",
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


# ── Get single document ───────────────────────────────────────────────────────

@router.get(
    "/subjects/{subjectId}/documents/{documentId}",
    summary="Get one document within the Tenant + Subject boundary",
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


# ── Document type summary ─────────────────────────────────────────────────────

@router.get(
    "/subjects/{subjectId}/document-types",
    summary="Count of accepted documents per document type for a Subject",
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
            documentTypes=[DocumentTypeCount(**c) for c in counts],
        ),
    )


# ── Delete ────────────────────────────────────────────────────────────────────

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


# ── Content / Fields / Quality — internal/ops endpoints ──────────────────────
# These return the same ApiResponse envelope per D8.

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
    summary="Return extracted field values for a confirmed document",
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
                text("SELECT confirmation_status FROM docintel.documents WHERE tenant_id=:tid AND document_id=:doc_id"),
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
                           dfv.confidence_score, dfv.version_no, dfv.accepted_at_utc
                    FROM docintel.document_field_values dfv
                    JOIN docintel.canonical_fields cf ON cf.canonical_field_id=dfv.canonical_field_id
                    WHERE dfv.tenant_id=:tid AND dfv.document_id=:doc_id AND dfv.is_current=true
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
                    "confidenceScore": float(r["confidence_score"]) if r.get("confidence_score") else None,
                    "versionNo": r["version_no"],
                    "acceptedAt": r["accepted_at_utc"].isoformat() if r.get("accepted_at_utc") else None,
                }
                for r in rows
            ],
        },
    )


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
                    "evaluatedAt": r["evaluated_at_utc"].isoformat() if r.get("evaluated_at_utc") else None,
                }
                for r in rows
            ],
        },
    )


@router.get(
    "/subjects/{subjectId}/document-exceptions",
    operation_id="getSubjectDocumentExceptions",
    summary="List exception documents for a Subject",
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
                "registeredAt": r["registered_at_utc"].isoformat() if r.get("registered_at_utc") else None,
            }
            for r in rows
        ],
    )

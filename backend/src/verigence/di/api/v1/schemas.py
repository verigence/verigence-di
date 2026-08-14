"""api/v1/schemas.py — Pydantic request/response schemas.

D8:  Universal ApiResponse envelope — all endpoints return errorCode + errorMessage + data.
D9:  Upload request simplified — file + documentTypeKey only.
D11: Document responses slimmed to public fields only.
D12: New DocumentTypeSummary response for /document-types endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from verigence.di.domain.enums import (
    ConfirmationStatus,
    ProcessingStatus,
    SubjectStatus,
    SubjectType,
    UploadStatus,
)

T = TypeVar("T")


# ── Universal response envelope (D8) ─────────────────────────────────────────

class ApiResponse(BaseModel, Generic[T]):
    """Universal response envelope for all endpoints.

    errorCode: "000" = success; "E001"–"E010"+ = failure (see DI_DECISIONS.md D8).
    errorMessage: human-readable. "File Uploaded Successfully" / "Success" on success.
    data: payload on success; null on failure.
    """
    errorCode: str
    errorMessage: str
    data: T | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Public upload status helpers (D9) ─────────────────────────────────────────
# Internal DB values (FIT/NOT_FIT/CORRUPT/UPLOAD_FAILED) map to public ACCEPTED/REJECTED.

_INTERNAL_TO_PUBLIC_UPLOAD: dict[UploadStatus, str] = {
    UploadStatus.FIT: "ACCEPTED",
    UploadStatus.NOT_FIT: "REJECTED",
    UploadStatus.CORRUPT: "REJECTED",
    UploadStatus.UPLOAD_FAILED: "REJECTED",
    UploadStatus.RECEIVING: "PENDING",
    UploadStatus.VALIDATING: "PENDING",
}

# Internal processing status → public value (D9)
_INTERNAL_TO_PUBLIC_PROCESSING: dict[ProcessingStatus, str | None] = {
    ProcessingStatus.NOT_STARTED: "PENDING",
    ProcessingStatus.PROCESSING: "PROCESSING",
    ProcessingStatus.RETRY_PENDING: "PENDING",
    ProcessingStatus.PROCESSED: "PROCESSED",
    ProcessingStatus.FAILED: "FAILED",
}


def public_upload_status(internal: UploadStatus) -> str:
    return _INTERNAL_TO_PUBLIC_UPLOAD.get(internal, "REJECTED")


def public_processing_status(internal: ProcessingStatus | None, upload_rejected: bool) -> str | None:
    if upload_rejected:
        return None
    if internal is None:
        return None
    return _INTERNAL_TO_PUBLIC_PROCESSING.get(internal)


# ── Document schemas (D9, D11) ────────────────────────────────────────────────

class UploadData(BaseModel):
    """Payload inside ApiResponse for POST /documents (D9)."""
    documentId: uuid.UUID
    uploadStatus: str          # "ACCEPTED" | "REJECTED"
    processingStatus: str | None = None  # "PENDING" | "PROCESSING" | "PROCESSED" | "FAILED" | null

    model_config = ConfigDict(from_attributes=True)


class DocumentData(BaseModel):
    """Slim document object returned in GET responses (D11)."""
    documentId: uuid.UUID
    documentTypeKey: str | None = None
    uploadStatus: str          # "ACCEPTED" | "REJECTED"
    processingStatus: str | None = None
    confirmationStatus: ConfirmationStatus | None = None
    confidenceScore: Decimal | None = None
    registeredAtUtc: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListData(BaseModel):
    """Payload inside ApiResponse for GET /documents (list)."""
    subjectId: uuid.UUID
    totalDocuments: int
    documents: list[DocumentData] = []

    model_config = ConfigDict(from_attributes=True)


class DocumentTypeCount(BaseModel):
    documentTypeKey: str
    count: int


class DocumentTypeSummaryData(BaseModel):
    """Payload inside ApiResponse for GET /document-types (D12)."""
    subjectId: uuid.UUID
    documentTypes: list[DocumentTypeCount] = []

    model_config = ConfigDict(from_attributes=True)


# ── Subject schemas (unchanged) ───────────────────────────────────────────────

class CreateSubjectRequest(BaseModel):
    """POST /v1/tenants/{tenantId}/subjects body."""
    subjectType: SubjectType
    displayName: str | None = None


class SubjectResponse(BaseModel):
    """GET / POST Subject response — still wrapped in ApiResponse by the router."""
    tenantId: str
    subjectId: uuid.UUID
    subjectType: SubjectType
    displayName: str | None = None
    status: SubjectStatus
    createdAtUtc: datetime
    updatedAtUtc: datetime

    model_config = ConfigDict(from_attributes=True)


class SubjectListData(BaseModel):
    items: list[SubjectResponse]
    nextCursor: str | None = None


# ── Legacy aliases — kept for internal endpoints not yet migrated ─────────────
# (deletion.py, verification.py etc. that still use DocumentResponse directly)

class DocumentResponse(BaseModel):
    """Legacy full document response — used by internal/ops endpoints only.
    Public document endpoints now use DocumentData inside ApiResponse.
    """
    tenantId: str
    documentId: uuid.UUID
    subjectId: uuid.UUID | None = None
    uploadStatus: UploadStatus
    processingStatus: ProcessingStatus
    confirmationStatus: ConfirmationStatus
    confidenceScore: Decimal | None = None
    verificationState: Any = None
    contentState: Any = None
    originalFilename: str | None = None
    declaredMimeType: str | None = None
    detectedMimeType: str | None = None
    fileSizeBytes: int | None = None
    contentHashSha256: str | None = None
    pageCount: int | None = None
    correlationId: str | None = None
    registeredAtUtc: datetime | None = None
    processedAtUtc: datetime | None = None
    confirmedAtUtc: datetime | None = None
    uploadIssueCode: str | None = None
    uploadIssueDetail: str | None = None
    processingFailureCode: str | None = None
    duplicateOfDocumentId: uuid.UUID | None = None
    replacesDocumentId: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class SubjectDocumentView(BaseModel):
    """Legacy — used by internal ops only."""
    tenantId: str
    subjectId: uuid.UUID
    configurationStatus: str
    requirementProfileId: uuid.UUID | None = None
    requirementProfileVersion: int | None = None
    documents: list[DocumentResponse] = []
    totalDocuments: int = 0

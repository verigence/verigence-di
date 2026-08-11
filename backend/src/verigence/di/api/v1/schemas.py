"""api/v1/schemas.py — Pydantic request/response schemas (Baseline 2.2).

All schemas use camelCase to match the OAS contract.

v2.2 Problem schema adds: code (stable), retryable, category, correlationId.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from verigence.di.domain.enums import (
    ConfirmationStatus,
    ContentState,
    HumanVerificationStatus,
    ProcessingStatus,
    SourceChannel,
    SubjectStatus,
    SubjectType,
    UploadStatus,
    VerificationState,
)

# ── Shared config: camelCase aliases for OAS compliance ──────────────────────

class _CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=None,  # we set aliases manually
        from_attributes=True,
    )


# ── Problem (RFC 7807 + DI v2.2 extensions) ──────────────────────────────────

class Problem(BaseModel):
    """v2.2 Problem body. Clients MUST branch on `code`, never on `title`."""
    type: str = "about:blank"
    code: str                           # stable DI error code (e.g. FILE_TOO_LARGE)
    title: str
    status: int
    retryable: bool = False             # from DI_ERROR_CATALOG_v2.2.yaml
    category: str | None = None         # error category group
    detail: str | None = None
    instance: str | None = None
    correlationId: str | None = None    # echoed X-Correlation-ID
    extensions: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


# ── Subject ───────────────────────────────────────────────────────────────────

class CreateSubjectRequest(BaseModel):
    """POST /v1/tenants/{tenantId}/subjects body."""
    subjectType: SubjectType
    displayName: str | None = Field(None, max_length=240)


class SubjectResponse(BaseModel):
    """GET / POST Subject response."""
    tenantId: str
    subjectId: uuid.UUID
    subjectType: SubjectType
    displayName: str | None = None
    status: SubjectStatus
    createdAtUtc: datetime
    updatedAtUtc: datetime

    model_config = ConfigDict(from_attributes=True)


class SubjectListResponse(BaseModel):
    items: list[SubjectResponse]
    nextCursor: str | None = None


# ── Document ──────────────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    """Document state returned from upload / GET document."""
    tenantId: str
    documentId: uuid.UUID
    subjectId: uuid.UUID | None = None
    sourceChannel: SourceChannel
    uploadStatus: UploadStatus
    processingStatus: ProcessingStatus
    confirmationStatus: ConfirmationStatus
    confidenceScore: Decimal | None = None
    verificationThresholdApplied: Decimal | None = None
    humanVerificationStatus: HumanVerificationStatus | None = None
    verificationState: VerificationState
    contentState: ContentState
    originalFilename: str | None = None
    declaredMimeType: str | None = None
    detectedMimeType: str | None = None
    fileSizeBytes: int | None = None
    contentHashSha256: str | None = None
    pageCount: int | None = None
    correlationId: str
    registeredAtUtc: datetime
    processedAtUtc: datetime | None = None
    confirmedAtUtc: datetime | None = None
    uploadIssueCode: str | None = None
    uploadIssueDetail: str | None = None
    processingFailureCode: str | None = None
    duplicateOfDocumentId: uuid.UUID | None = None
    replacesDocumentId: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Subject document view ─────────────────────────────────────────────────────

class SubjectDocumentView(BaseModel):
    """GET /v1/tenants/{tenantId}/subjects/{subjectId}/documents response."""
    tenantId: str
    subjectId: uuid.UUID
    configurationStatus: str  # REQUIREMENT_PROFILE_NOT_ASSIGNED | PROFILE_ASSIGNED
    requirementProfileId: uuid.UUID | None = None
    requirementProfileVersion: int | None = None
    documents: list[DocumentResponse] = []
    totalDocuments: int = 0

"""errors.py — Canonical error/Problem code catalogue (Baseline 2.2).

Source of truth: DI_ERROR_CATALOG_v2.2.yaml / DI_ERROR_CATALOG_v2.2.md

Usage::

    from verigence.di.errors import problem_response, ErrorCode

    raise HTTPException(
        status_code=ErrorCode.FILE_TOO_LARGE.http_status,
        detail=problem_response(ErrorCode.FILE_TOO_LARGE, detail="..."),
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _ErrorDef:
    code: str
    http_status: int
    retryable: bool
    category: str
    title: str


class ErrorCode:
    """All 38 canonical DI error codes from DI_ERROR_CATALOG_v2.2.yaml.
    Additional convenience aliases added for common HTTP patterns.
    """

    INVALID_REQUEST                  = _ErrorDef("INVALID_REQUEST",                  400, False, "REQUEST",          "Request syntax/parameters/body are invalid.")
    UNAUTHORIZED                     = _ErrorDef("UNAUTHORIZED",                     401, False, "AUTHENTICATION",   "JWT is absent, invalid, expired, or required claims are missing.")
    FORBIDDEN                        = _ErrorDef("FORBIDDEN",                        403, False, "AUTHORIZATION",    "Authenticated actor lacks the required permission or Tenant/resource scope.")
    TENANT_NOT_FOUND                 = _ErrorDef("TENANT_NOT_FOUND",                 404, False, "TENANT",           "Tenant does not exist or is not visible to the caller.")
    TENANT_NOT_READY                 = _ErrorDef("TENANT_NOT_READY",                 409, False, "CONFIGURATION",    "Tenant activation prerequisites are incomplete.")
    RETENTION_POLICY_NOT_CONFIGURED  = _ErrorDef("RETENTION_POLICY_NOT_CONFIGURED",  409, False, "CONFIGURATION",    "Required active retention policy is missing.")
    DEVICE_NOT_REGISTERED            = _ErrorDef("DEVICE_NOT_REGISTERED",            403, False, "AUTHORIZATION",    "USER token device_id is missing, revoked, or not registered.")
    REQUIREMENT_PROFILE_NOT_ASSIGNED = _ErrorDef("REQUIREMENT_PROFILE_NOT_ASSIGNED", 409, False, "CONFIGURATION",    "Subject has no active Requirement Profile assignment.")
    REQUIREMENT_PROFILE_NOT_PUBLISHED= _ErrorDef("REQUIREMENT_PROFILE_NOT_PUBLISHED",409, False, "CONFIGURATION",    "Requested Requirement Profile is not in PUBLISHED state.")
    DOCUMENT_TYPE_NOT_FOUND          = _ErrorDef("DOCUMENT_TYPE_NOT_FOUND",          404, False, "CONFIGURATION",    "Document Type key/resource is not visible or does not exist.")
    EXTRACTION_PROFILE_NOT_FOUND     = _ErrorDef("EXTRACTION_PROFILE_NOT_FOUND",     404, False, "CONFIGURATION",    "Requested/effective Extraction Profile does not exist.")
    SUBJECT_DOCUMENT_NOT_FOUND       = _ErrorDef("SUBJECT_DOCUMENT_NOT_FOUND",       404, False, "RESOURCE",         "No matching Document exists inside the supplied Tenant + Subject boundary.")
    DOCUMENT_NOT_CONFIRMED           = _ErrorDef("DOCUMENT_NOT_CONFIRMED",           409, False, "STATE",            "Requested operation requires machine CONFIRMED state.")
    DOCUMENT_CONTENT_PURGED          = _ErrorDef("DOCUMENT_CONTENT_PURGED",          410, False, "RETENTION",        "Document content was purged under retention policy.")
    IDEMPOTENCY_CONFLICT             = _ErrorDef("IDEMPOTENCY_CONFLICT",             409, False, "IDEMPOTENCY",      "Same idempotency key reused with a different request payload.")
    FILE_EMPTY                       = _ErrorDef("FILE_EMPTY",                       422, False, "UPLOAD",           "Uploaded file contains zero bytes.")
    FILE_TOO_LARGE                   = _ErrorDef("FILE_TOO_LARGE",                   413, False, "UPLOAD",           "File exceeds configured Tenant limit.")
    MIME_TYPE_NOT_ALLOWED            = _ErrorDef("MIME_TYPE_NOT_ALLOWED",            415, False, "UPLOAD",           "Declared/detected MIME type is not allowed.")
    INVALID_FILE_CONTENT             = _ErrorDef("INVALID_FILE_CONTENT",             422, False, "UPLOAD",           "File signature/parser/structure validation failed.")
    INVALID_CONFIGURATION            = _ErrorDef("INVALID_CONFIGURATION",            409, False, "CONFIGURATION",    "Configuration fails a deterministic invariant.")
    DOCUMENT_NOT_FOUND               = _ErrorDef("DOCUMENT_NOT_FOUND",              404, False, "RESOURCE",          "Document resource does not exist or is not visible.")
    UNASSIGNED_DOCUMENT_NOT_FOUND    = _ErrorDef("UNASSIGNED_DOCUMENT_NOT_FOUND",    404, False, "RESOURCE",         "Unassigned Tenant Document does not exist or is not visible.")
    SUBJECT_DOCUMENT_MISMATCH        = _ErrorDef("SUBJECT_DOCUMENT_MISMATCH",        404, False, "RESOURCE",         "Document does not belong to the supplied Subject boundary.")
    INVALID_DOCUMENT_STATE           = _ErrorDef("INVALID_DOCUMENT_STATE",           409, False, "STATE",            "Requested state transition/action is not valid for current Document state.")
    DOCUMENT_REPLACEMENT_NOT_ALLOWED = _ErrorDef("DOCUMENT_REPLACEMENT_NOT_ALLOWED", 409, False, "STATE",            "Replacement allowed only for NOT_FIT, CORRUPT or UPLOAD_FAILED evidence.")
    DOCUMENT_ALREADY_ASSIGNED        = _ErrorDef("DOCUMENT_ALREADY_ASSIGNED",        409, False, "STATE",            "Unassigned Document already has a Subject.")
    PROFILE_IMMUTABLE                = _ErrorDef("PROFILE_IMMUTABLE",                409, False, "CONFIGURATION",    "Published/retired profile content is immutable.")
    PROFILE_NOT_DRAFT                = _ErrorDef("PROFILE_NOT_DRAFT",                409, False, "CONFIGURATION",    "Requested profile mutation requires DRAFT state.")
    WHATSAPP_ROUTE_NOT_FOUND         = _ErrorDef("WHATSAPP_ROUTE_NOT_FOUND",         404, False, "INTEGRATION",      "No configured Tenant route matches the WhatsApp identity.")
    QUARANTINE_ITEM_NOT_FOUND        = _ErrorDef("QUARANTINE_ITEM_NOT_FOUND",        404, False, "INTEGRATION",      "System quarantine item does not exist or is no longer actionable.")
    STORAGE_WRITE_FAILED             = _ErrorDef("STORAGE_WRITE_FAILED",             503, True,  "DEPENDENCY",       "Object-storage write failed transiently.")
    STORAGE_READ_FAILED              = _ErrorDef("STORAGE_READ_FAILED",              503, True,  "DEPENDENCY",       "Object-storage read failed transiently.")
    QUALITY_POLICY_NOT_CONFIGURED    = _ErrorDef("QUALITY_POLICY_NOT_CONFIGURED",    409, False, "CONFIGURATION",    "Tenant quality policy is absent/invalid.")
    CLASSIFICATION_NO_CANDIDATES     = _ErrorDef("CLASSIFICATION_NO_CANDIDATES",     409, False, "CLASSIFICATION",   "Candidate formation produced no processing-ready Document Type.")
    CLASSIFICATION_AMBIGUOUS         = _ErrorDef("CLASSIFICATION_AMBIGUOUS",         422, False, "CLASSIFICATION",   "Classification did not yield exactly one acceptable candidate.")
    SUBJECT_MATCH_AMBIGUOUS          = _ErrorDef("SUBJECT_MATCH_AMBIGUOUS",          409, False, "SUBJECT_MATCHING", "Identity evidence maps to more than one candidate Subject.")
    SUBJECT_IDENTIFIER_CONFLICT      = _ErrorDef("SUBJECT_IDENTIFIER_CONFLICT",      409, False, "SUBJECT_MATCHING", "Active VERIFIED identifier already belongs to another Subject.")
    INTERNAL_ERROR                   = _ErrorDef("INTERNAL_ERROR",                   500, True,  "INTERNAL",         "Unexpected server error.")

    # ── Convenience aliases / additional codes for API layer ─────────────────
    SUBJECT_NOT_FOUND                = _ErrorDef("SUBJECT_NOT_FOUND",                404, False, "RESOURCE",         "Subject does not exist or is not visible to the caller.")
    VALIDATION_ERROR                 = _ErrorDef("VALIDATION_ERROR",                 422, False, "REQUEST",          "Request body failed validation.")
    CONFLICT                         = _ErrorDef("CONFLICT",                          409, False, "STATE",            "Request conflicts with existing resource state.")
    INVALID_PROFILE_STATE            = _ErrorDef("INVALID_PROFILE_STATE",            409, False, "CONFIGURATION",    "Profile mutation requires DRAFT state.")
    REQUIREMENT_PROFILE_NOT_FOUND    = _ErrorDef("REQUIREMENT_PROFILE_NOT_FOUND",    404, False, "CONFIGURATION",    "Requirement Profile does not exist.")
    RETENTION_POLICY_NOT_FOUND       = _ErrorDef("RETENTION_POLICY_NOT_FOUND",       404, False, "RESOURCE",         "Retention Policy does not exist.")
    INVALID_DOCUMENT_TYPE_STATE      = _ErrorDef("INVALID_DOCUMENT_TYPE_STATE",      409, False, "CONFIGURATION",    "Document Type state does not allow this operation.")
    STORAGE_READ_ERROR               = _ErrorDef("STORAGE_READ_ERROR",               503, True,  "DEPENDENCY",       "Object-storage read failed transiently.")
    DOCUMENT_NOT_ELIGIBLE_FOR_DELETE = _ErrorDef("DOCUMENT_NOT_ELIGIBLE_FOR_DELETE",  409, False, "STATE",            "Document does not meet the eligibility criteria for deletion.")


def problem_response(
    error: _ErrorDef,
    *,
    detail: str | None = None,
    instance: str | None = None,
    correlation_id: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2.2 Problem body dict.

    Clients MUST branch on ``code``; never on ``title`` or ``detail``.
    """
    body: dict[str, Any] = {
        "type": f"https://docs.verigence.app/errors/{error.code.lower()}",
        "code": error.code,
        "title": error.title,
        "status": error.http_status,
        "retryable": error.retryable,
        "category": error.category,
    }
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    if correlation_id:
        body["correlationId"] = correlation_id
    if extensions:
        body.update(extensions)
    return body


def http_exception(
    error: _ErrorDef,
    *,
    detail: str | None = None,
    correlation_id: str | None = None,
) -> Exception:
    """Build a FastAPI HTTPException with a canonical Problem body.

    Usage::
        raise http_exception(ErrorCode.FILE_TOO_LARGE, detail="max 30 MB")
    """
    from fastapi import HTTPException
    return HTTPException(
        status_code=error.http_status,
        detail=problem_response(error, detail=detail, correlation_id=correlation_id),
    )


def problem(
    http_status: int,
    detail: str,
    error: _ErrorDef,
    *,
    correlation_id: str | None = None,
) -> Exception:
    """Convenience shorthand — build and return (not raise) an HTTPException.

    Usage::
        raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)
    """
    from fastapi import HTTPException
    return HTTPException(
        status_code=error.http_status,
        detail=problem_response(error, detail=detail, correlation_id=correlation_id),
    )

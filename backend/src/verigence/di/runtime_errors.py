"""Safe runtime error classification and diagnostic helpers.

This module is deliberately small and dependency-light so API handlers, workers,
adapters and integrations can all use the same rules:

* never expose ``str(exc)`` as a client/business error;
* never put raw request/document/provider content in logs;
* never emit a full Python traceback;
* every failure event has a correlation id;
* preserve stable technical codes so operations can understand the failing layer.
"""
from __future__ import annotations

import os
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

import structlog


_MAX_STACK_FRAMES = 4


@dataclass(frozen=True)
class TechnicalFailure:
    """Caller-safe technical failure information."""

    code: str
    detail: str
    retryable: bool


def correlation_id_or_new(candidate: object | None = None) -> str:
    """Return an existing request/job correlation id or create one.

    Background failures do not always originate from an HTTP request.  They still
    need an identifier that operators can use to correlate the failure event with
    retries and persisted state.
    """
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()[:128]
    context_value = structlog.contextvars.get_contextvars().get("correlation_id")
    if isinstance(context_value, str) and context_value.strip():
        return context_value.strip()[:128]
    return str(uuid.uuid4())


def safe_exception_context(
    exc: BaseException,
    *,
    max_frames: int = _MAX_STACK_FRAMES,
) -> dict[str, Any]:
    """Return exception diagnostics without message, locals, source text or full stack.

    Only the exception class and a bounded list of code locations are emitted.
    This gives operations enough information to locate the failing code while
    preventing exception messages from leaking document values, request bodies,
    provider responses, tokens or database values.
    """
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ is not None else []
    limit = max(1, max_frames)
    selected = frames[-limit:]
    rendered = [
        f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
        for frame in selected
    ]
    return {
        "exception_type": type(exc).__name__,
        "stack_summary": rendered,
        "stack_truncated": len(frames) > len(selected),
    }


def technical_failure(
    exc: BaseException,
    *,
    operation: str,
    retryable: bool | None = None,
) -> TechnicalFailure:
    """Map an exception to a stable, safe technical code for ``operation``.

    The mapping intentionally uses exception *type/status*, never exception text.
    Explicit provider/integration exceptions can publish ``technical_code`` and
    ``retryable`` attributes; otherwise the operation identifies the failing
    subsystem.  Existing worker code names are retained where they already form
    part of persisted operational state.
    """
    explicit_code = getattr(exc, "technical_code", None)
    explicit_retryable = getattr(exc, "retryable", None)
    if isinstance(explicit_code, str) and explicit_code:
        return TechnicalFailure(
            code=explicit_code,
            detail=_detail_for_code(explicit_code),
            retryable=(
                bool(explicit_retryable)
                if isinstance(explicit_retryable, bool)
                else (True if retryable is None else retryable)
            ),
        )

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        if status_code == 429 and operation in {
            "classification_provider",
            "extraction_provider",
        }:
            return TechnicalFailure(
                "DOCUMENT_AI_RATE_LIMITED",
                _detail_for_code("DOCUMENT_AI_RATE_LIMITED"),
                True,
            )
        if status_code in {408, 500, 502, 503, 504} and operation in {
            "classification_provider",
            "extraction_provider",
        }:
            return TechnicalFailure(
                "DOCUMENT_AI_UNAVAILABLE",
                _detail_for_code("DOCUMENT_AI_UNAVAILABLE"),
                True,
            )

    exc_module = type(exc).__module__.lower()
    exc_name = type(exc).__name__.lower()
    if "sqlalchemy" in exc_module or "asyncpg" in exc_module or "database" in exc_name:
        return TechnicalFailure(
            "DATABASE_UNAVAILABLE",
            _detail_for_code("DATABASE_UNAVAILABLE"),
            True if retryable is None else retryable,
        )
    if "httpx" in exc_module or isinstance(exc, (ConnectionError, TimeoutError)):
        return TechnicalFailure(
            "DEPENDENCY_UNAVAILABLE",
            _detail_for_code("DEPENDENCY_UNAVAILABLE"),
            True if retryable is None else retryable,
        )

    operation_codes = {
        "classification_provider": "CLASSIFICATION_PROVIDER_ERROR",
        "extraction_provider": "EXTRACTION_PROVIDER_ERROR",
        "capture_v2_classification": "CLASSIFICATION_FAILED",
        "audit_core_link": "AUDIT_CORE_INTEGRATION_FAILED",
        "security_service": "SECURITY_INTEGRATION_FAILED",
        "worker": "WORKER_INTERNAL_ERROR",
        "processing": "WORKER_INTERNAL_ERROR",
        "api": "INTERNAL_ERROR",
    }
    code = operation_codes.get(operation, "INTERNAL_ERROR")
    return TechnicalFailure(
        code=code,
        detail=_detail_for_code(code),
        retryable=True if retryable is None else retryable,
    )


def safe_persisted_detail(code: str) -> str:
    """Return a bounded, caller-safe detail suitable for persisted failure state."""
    return _detail_for_code(code)[:500]


def validation_problem_detail(
    errors: list[dict[str, Any]],
) -> tuple[str, list[dict[str, str]]]:
    """Summarise Pydantic validation errors without echoing submitted values.

    Only schema locations and stable validation type identifiers are retained.
    Pydantic's ``input``, context and human message fields are deliberately not
    copied because they may contain caller-supplied data.
    """
    issues: list[dict[str, str]] = []
    for item in errors[:20]:
        raw_loc = item.get("loc")
        if isinstance(raw_loc, (tuple, list)):
            field = ".".join(str(part) for part in raw_loc if str(part))
        else:
            field = "request"
        issue_type = str(item.get("type") or "invalid")[:120]
        issues.append({"field": field[:240] or "request", "type": issue_type})
    if not issues:
        return "One or more request fields are invalid.", []
    fields = sorted({item["field"] for item in issues})
    preview = ", ".join(fields[:8])
    suffix = " and additional fields" if len(fields) > 8 else ""
    return f"Request validation failed for {preview}{suffix}.", issues


def _catalogue_title(code: str) -> str | None:
    """Resolve an existing ErrorCode title without coupling to its private type."""
    from verigence.di.errors import ErrorCode

    for name in dir(ErrorCode):
        if name.startswith("_"):
            continue
        candidate = getattr(ErrorCode, name)
        if getattr(candidate, "code", None) == code:
            title = getattr(candidate, "title", None)
            if isinstance(title, str) and title:
                return title
    return None


def _detail_for_code(code: str) -> str:
    details = {
        "INTERNAL_ERROR": "An unexpected technical error occurred. Use the correlation ID when contacting support.",
        "WORKER_INTERNAL_ERROR": "Document processing failed due to an internal technical error. The operation may be retried where safe.",
        "DATABASE_UNAVAILABLE": "The database is temporarily unavailable. The operation may be retried where safe.",
        "DEPENDENCY_UNAVAILABLE": "A required downstream service is temporarily unavailable. The operation may be retried where safe.",
        "DOCUMENT_AI_UNAVAILABLE": "The Document AI provider is temporarily unavailable. Processing may be retried automatically.",
        "DOCUMENT_AI_RATE_LIMITED": "The Document AI provider is temporarily rate limited. Processing may be retried automatically.",
        "DOCUMENT_AI_RESPONSE_INVALID": "The Document AI provider returned an unusable response. Processing may be retried automatically.",
        "CLASSIFICATION_PROVIDER_ERROR": "The document classification provider request failed. Processing may be retried automatically.",
        "EXTRACTION_PROVIDER_ERROR": "The document extraction provider request failed. Processing may be retried automatically.",
        "CLASSIFICATION_FAILED": "Document classification could not be completed after the permitted attempts.",
        "CLASSIFICATION_RETRY": "Document classification failed temporarily and has been scheduled for retry.",
        "AUDIT_CORE_INTEGRATION_FAILED": "Audit Core document linkage could not be completed. Delivery will be retried according to policy.",
        "SECURITY_INTEGRATION_FAILED": "Security service authorization could not be completed. The integration may be retried where safe.",
        "NOTIFY_LISTENER_UNAVAILABLE": "Database notification listener is unavailable; polling fallback is active.",
        "STARTUP_VALIDATION_FAILED": "A non-blocking startup consistency check failed; runtime startup continued.",
        "EXTRACTION_PROFILE_EMPTY": "The effective extraction profile contains no enabled fields.",
        "SCORING_DENOMINATOR_ZERO": "The extraction profile scoring configuration has no positive denominator.",
        "UPLOAD_NOT_FIT": "The uploaded document failed file-quality validation.",
    }
    explicit = details.get(code)
    if explicit is not None:
        return explicit
    catalogue = _catalogue_title(code)
    if catalogue is not None:
        return catalogue
    return "A technical error occurred. Use the error code and correlation ID for diagnosis."

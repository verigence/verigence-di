"""retry_policy.py — how often a Capture V2 page is tried again, and when.

Product owner's rule (2026-10-20): fewer attempts.

* AI failure (the Gemini call gave no usable answer: rate limited, model
  unavailable or timed out, empty or unparseable answer): the page is tried
  again 10 minutes after the first failure and 20 minutes after the second,
  three attempts in all. If it still fails, and the page passed DI's upload
  scan, it is left for one more attempt the same night (scheduler/beat.py);
  the PC is not asked to do anything until that night attempt has failed too.
* Technical failure inside DI (storage read, database, an internal error):
  two attempts in all, the second two minutes after the first; then the page
  is FAILED and Audit Core tells the PC.
* A failure the page itself decides (scan rejection, unreadable file, a
  content refusal) or a configuration gap is never retried.

The same ladder applies to classification (capture_v2_classifier) and
extraction (processor); the Gemini adapters themselves never retry, so the
attempts here are the only ones.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from verigence.di.runtime_errors import BUSINESS_FAILURE_CODES, CONFIGURATION_FAILURE_CODES

# Gemini answered with nothing usable, for a reason a later call can change.
AI_RETRYABLE_FAILURE_CODES = frozenset(
    {
        "DOCUMENT_AI_RATE_LIMITED",
        "DOCUMENT_AI_UNAVAILABLE",
        "DOCUMENT_AI_RESPONSE_INVALID",
        "CLASSIFICATION_PROVIDER_ERROR",
        "EXTRACTION_PROVIDER_ERROR",
    }
)
# Gemini refused the request itself (a 4xx other than 429): the same request
# is refused again, so it is an AI failure that is never retried.
AI_FAILURE_CODES = AI_RETRYABLE_FAILURE_CODES | {"DOCUMENT_AI_REQUEST_REJECTED"}

# Seconds to wait after attempt 1, 2, ... failed.
AI_RETRY_DELAYS_SECONDS: tuple[int, ...] = (600, 1200)
TECHNICAL_RETRY_DELAYS_SECONDS: tuple[int, ...] = (120,)
AI_MAX_ATTEMPTS = len(AI_RETRY_DELAYS_SECONDS) + 1
TECHNICAL_MAX_ATTEMPTS = len(TECHNICAL_RETRY_DELAYS_SECONDS) + 1

# The classification job's attempt number for the one night attempt: one past
# the daytime ladder, so a failure of it is final at once.
CLASSIFICATION_NIGHT_ATTEMPT_NO = AI_MAX_ATTEMPTS + 1

# What failed, as Audit Core needs to know it (the listing's failureKind).
AI = "AI"
TECHNICAL = "TECHNICAL"
DOCUMENT = "DOCUMENT"
CONFIGURATION = "CONFIGURATION"

_DOCUMENT_CODES = BUSINESS_FAILURE_CODES | {"CORRUPT", "UPLOAD_FAILED", "UPLOAD_NOT_FIT"}


def failure_kind(code: str | None) -> str | None:
    """AI / TECHNICAL / DOCUMENT / CONFIGURATION for a stored failure code;
    None when there is no code."""
    if not code:
        return None
    code = code.upper()
    if code in AI_FAILURE_CODES:
        return AI
    if code.startswith("DI_QUALITY_") or code in _DOCUMENT_CODES:
        return DOCUMENT
    if code in CONFIGURATION_FAILURE_CODES:
        return CONFIGURATION
    return TECHNICAL


_SCAN_FAILED_STATUSES = frozenset({"NOT_FIT", "CORRUPT", "UPLOAD_FAILED"})


def scan_passed(upload_status: str | None) -> bool | None:
    """Whether the page passed DI's upload scan (integrity and scan-quality
    rules, quality/validator.py): True when FIT, False when rejected, None
    while the scan has not run (the file is still arriving or being checked)."""
    if upload_status == "FIT":
        return True
    if upload_status in _SCAN_FAILED_STATUSES:
        return False
    return None


def retry_status(row: Mapping[str, Any]) -> dict[str, Any]:
    """What the status listing says about a page's failures and retries.

    ``row`` carries the upload's state and failure_code, the document's
    upload_status, processing_status and processing_failure_code, the
    classification job's status, attempt number, error code and due time,
    the next pending processing job's due time, and whether the document
    already had its night attempt (night_reprocess_used).

    Returns failureKind (of the final failure, or of the failed attempt a
    pending retry follows), the failure code behind it, nextAttemptAtUtc for
    a pending daytime retry, retryTonight when the page is FAILED and the
    nightly run will try it once more, and scanPassed."""
    passed = scan_passed(row.get("upload_status"))
    state = str(row.get("state") or "")
    processing = str(row.get("processing_status") or "")
    code: str | None = None
    next_at: Any = None
    tonight = False
    if state == "FAILED":
        code = row.get("failure_code")
        tonight = (
            passed is True
            and (code or "") in AI_RETRYABLE_FAILURE_CODES
            and int(row.get("classification_attempt_no") or 0) < CLASSIFICATION_NIGHT_ATTEMPT_NO
        )
    elif state in ("STORED", "CLASSIFYING"):
        if row.get("classification_job_status") == "PENDING" and int(row.get("classification_attempt_no") or 1) > 1:
            code = row.get("classification_error_code")
            next_at = row.get("classification_due_at_utc")
    elif state == "CLASSIFIED":
        if processing == "RETRY_PENDING":
            code = row.get("processing_failure_code")
            next_at = row.get("processing_next_due_at_utc")
        elif processing == "FAILED":
            code = row.get("processing_failure_code")
            tonight = (
                passed is True
                and (code or "") in AI_RETRYABLE_FAILURE_CODES
                and not row.get("night_reprocess_used")
            )
    return {
        "scanPassed": passed,
        "failureKind": failure_kind(code),
        "retryFailureCode": code,
        "nextAttemptAtUtc": next_at,
        "retryTonight": tonight,
    }


def retry_delay_seconds(code: str | None, *, retryable: bool, attempt_no: int) -> int | None:
    """Seconds until the next daytime attempt after attempt ``attempt_no``
    (numbered from 1) failed with ``code``, or None when the daytime attempts
    are used up or a retry cannot help."""
    if not retryable or attempt_no < 1:
        return None
    kind = failure_kind(code)
    if kind in (DOCUMENT, CONFIGURATION):
        return None
    delays = (
        AI_RETRY_DELAYS_SECONDS
        if kind == AI and (code or "").upper() in AI_RETRYABLE_FAILURE_CODES
        else TECHNICAL_RETRY_DELAYS_SECONDS
    )
    return delays[attempt_no - 1] if attempt_no <= len(delays) else None

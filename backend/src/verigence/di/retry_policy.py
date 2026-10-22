"""retry_policy.py — how often a Capture V2 page is tried again, and when.

Product owner's rule (2026-10-21 12:24 IST, replacing the night attempt of
2026-10-20): "only two attempts in 10 and 20 minutes", and no file may take
more than 30 minutes (Audit Core fails any page still not read then).
Since 2026-10-22 nothing is processed at night at all: the nightly
reprocessing run, and the one night re-read of a page our setup refused, are
gone (the listing's inNightAttempt and retryTonight stay in the response,
always false, so Audit Core versions on either side of this change agree).

* A failure a later call can fix -- an AI failure (the Gemini call gave no
  usable answer: rate limited, model unavailable or timed out, empty or
  unparseable answer) or a technical one (storage read, database, an internal
  error): first attempt at T0, retried at T0+10 minutes and T0+20 minutes,
  then FAILED. No night attempt: Audit Core raises the PC's "Document to
  resubmit" task, and clears the failed page from the Journey at the end of
  the day.
* A failure the page itself decides (scan rejection, unreadable file, a
  content refusal) or a configuration gap is never retried.
* Gemini refusing our key or model (DOCUMENT_AI_NOT_CONFIGURED) is our setup,
  not the page: it is never retried and fails at once; the PC uploads the
  page again once an administrator has fixed the setup (2026-10-22: it is no
  longer read again overnight).

One budget per document (2026-10-21 review): classification and extraction
share the three attempts. A page identified on its second attempt reads
as attempt 2 of the budget (budget_attempt: the reading job's own number
plus the identification attempts that failed), so T0, T0+10 and T0+20 are
the whole budget, never three for each step. And no retry starts later than 25 minutes after DI first received
the page, so every attempt runs inside Audit Core's 30-minute ceiling. The
Gemini adapters themselves never retry, so the attempts here are the only
ones.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
# Gemini refused the request itself (a 4xx other than 401/403/404/429): the
# same request is refused again, so it is an AI failure that is never retried.
AI_FAILURE_CODES = AI_RETRYABLE_FAILURE_CODES | {"DOCUMENT_AI_REQUEST_REJECTED"}
# Seconds to wait after attempt 1, 2, ... failed: T0, T0+10 min, T0+20 min.
AI_RETRY_DELAYS_SECONDS: tuple[int, ...] = (600, 600)
TECHNICAL_RETRY_DELAYS_SECONDS: tuple[int, ...] = (600, 600)
AI_MAX_ATTEMPTS = len(AI_RETRY_DELAYS_SECONDS) + 1
TECHNICAL_MAX_ATTEMPTS = len(TECHNICAL_RETRY_DELAYS_SECONDS) + 1
# No retry starts later than this after DI first received the page, so the
# last attempt finishes inside Audit Core's 30-minute ceiling.
LAST_RETRY_START_SECONDS = 25 * 60

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
    and the earliest pending-or-running processing job's due time.

    Returns failureKind (of the final failure, or of the failed attempt a
    pending retry follows), the failure code behind it, nextAttemptAtUtc
    whenever DI holds another attempt queued or running (a daytime retry, a
    person's Read again), scanPassed, and inNightAttempt and retryTonight,
    which are always False: there is no night attempt since 2026-10-22 (the
    fields remain so that Audit Core, on either side of this change, reads
    the same response).

    attemptsMade (2026-10-21): how many attempts of the document's one
    budget have been made -- the identification attempts, plus the reading
    attempts once the page was classified -- for Audit Core's failure report.
    """
    passed = scan_passed(row.get("upload_status"))
    state = str(row.get("state") or "")
    processing = str(row.get("processing_status") or "")
    code: str | None = None
    next_at: Any = None
    classification_attempt = int(row.get("classification_attempt_no") or 1)
    attempts = classification_attempt if row.get("classification_job_status") else None
    classification_in_hand = row.get("classification_job_status") in ("PENDING", "RUNNING")
    if state == "FAILED":
        code = row.get("failure_code")
    elif state in ("STORED", "CLASSIFYING"):
        if classification_in_hand and classification_attempt > 1:
            code = row.get("classification_error_code")
            next_at = row.get("classification_due_at_utc")
    elif state == "CLASSIFIED" and processing in ("RETRY_PENDING", "FAILED"):
        reading = int(row.get("processing_attempts") or 0)
        attempts = budget_attempt(reading, classification_attempt) if reading else None
        code = row.get("processing_failure_code")
        next_at = row.get("processing_next_due_at_utc")
    return {
        "scanPassed": passed,
        "failureKind": failure_kind(code),
        "retryFailureCode": code,
        "nextAttemptAtUtc": next_at,
        "inNightAttempt": False,
        "retryTonight": False,
        "attemptsMade": attempts,
    }


def budget_attempt(reading_attempt_no: int, classification_attempt_no: int | None) -> int:
    """Where a reading attempt stands in the document's one budget: its own
    number plus the identification attempts that failed before it."""
    return int(reading_attempt_no) + max(0, int(classification_attempt_no or 1) - 1)


def retry_delay_seconds(
    code: str | None,
    *,
    retryable: bool,
    attempt_no: int,
    received_at: datetime | None = None,
    now: datetime | None = None,
) -> int | None:
    """Seconds until the next daytime attempt after attempt ``attempt_no``
    (numbered from 1, across classification and extraction) failed with
    ``code``, or None when the attempts are used up, a retry cannot help,
    or the retry would start more than LAST_RETRY_START_SECONDS after the
    page was first received (``received_at``)."""
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
    if attempt_no > len(delays):
        return None
    delay = delays[attempt_no - 1]
    if received_at is not None:
        now = now or datetime.now(UTC)
        if now + timedelta(seconds=delay) > received_at + timedelta(seconds=LAST_RETRY_START_SECONDS):
            return None
    return delay

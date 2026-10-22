"""Product owner's retry rule (2026-10-21, no night attempt since 2026-10-22)
against the real schema: a Capture V2 page whose AI reading failed gets a
second daytime retry (attempt 3) and then fails; the EOD scheduler never
stacks a retry on a V2 page; the status listing says what failed and what
happens next, and never announces a night attempt.

Every test runs inside the db_session transaction, which is rolled back.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_nightly_once_and_reaper import _classified_unqueued_upload, _job, _jobs_for
from verigence.di.repositories.processing_jobs import schedule_v2_fast_retry
from verigence.di.retry_policy import retry_status
from verigence.di.scheduler import beat


async def _v2_page_failed_reading(session: AsyncSession, tenant_id: str, code: str) -> uuid.UUID:
    """A classified V2 page whose reading failed after its daytime attempts."""
    document_id = await _classified_unqueued_upload(session, tenant_id)
    await _job(session, tenant_id, document_id, job_type="INITIAL", attempt_no=1, status="FAILED")
    await _job(session, tenant_id, document_id, job_type="V2_FAST_RETRY", attempt_no=2, status="FAILED")
    await _job(session, tenant_id, document_id, job_type="V2_FAST_RETRY", attempt_no=3, status="FAILED")
    await session.execute(
        text("UPDATE docintel.documents SET processing_status='FAILED', confirmation_status='NOT_CONFIRMED', "
             "processing_failure_code=:code WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id, "code": code},
    )
    return document_id


async def _v2_page_failed_classification(
    session: AsyncSession, tenant_id: str, code: str, *, attempt_no: int = 3, upload_status: str = "FIT",
) -> uuid.UUID:
    document_id = await _classified_unqueued_upload(session, tenant_id)
    await session.execute(
        text("UPDATE docintel.document_capture_v2_uploads SET state='FAILED', failure_code=:code, "
             "classified_document_type_key=NULL WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id, "code": code},
    )
    await session.execute(
        text("UPDATE docintel.documents SET upload_status=:s WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id, "s": upload_status},
    )
    await session.execute(
        text("INSERT INTO docintel.document_capture_v2_classification_jobs "
             "(tenant_id, document_id, job_status, attempt_no, error_code) VALUES (:t, :d, 'FAILED', :a, :code)"),
        {"t": tenant_id, "d": document_id, "a": attempt_no, "code": code},
    )
    return document_id


async def _classification(session: AsyncSession, tenant_id: str, document_id: uuid.UUID) -> tuple[Any, ...]:
    return tuple((await session.execute(
        text("SELECT j.job_status, j.attempt_no, u.state FROM docintel.document_capture_v2_classification_jobs j "
             "JOIN docintel.document_capture_v2_uploads u ON u.tenant_id=j.tenant_id AND u.document_id=j.document_id "
             "WHERE j.tenant_id=:t AND j.document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )).one())


@pytest.mark.asyncio
async def test_the_second_daytime_retry_is_attempt_three(db_session: AsyncSession) -> None:
    tenant_id = f"v2-fast-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await _job(db_session, tenant_id, document_id, job_type="INITIAL", attempt_no=1, status="FAILED")
    await schedule_v2_fast_retry(db_session, tenant_id=tenant_id, document_id=document_id,
                                 correlation_id="c", attempt_no=2, delay_seconds=600)
    await schedule_v2_fast_retry(db_session, tenant_id=tenant_id, document_id=document_id,
                                 correlation_id="c", attempt_no=3, delay_seconds=1200)
    jobs = [tuple(j)[:3] for j in await _jobs_for(db_session, tenant_id, document_id)]
    assert jobs == [("INITIAL", 1, "FAILED"), ("V2_FAST_RETRY", 2, "PENDING"), ("V2_FAST_RETRY", 3, "PENDING")]
    due = (await db_session.execute(
        text("SELECT due_at_utc - created_at_utc FROM docintel.processing_jobs "
             "WHERE tenant_id=:t AND document_id=:d AND attempt_no=3"),
        {"t": tenant_id, "d": document_id},
    )).scalar_one()
    assert due == timedelta(seconds=1200)


@pytest.mark.asyncio
async def test_eod_retry_never_stacks_on_a_v2_page(db_session: AsyncSession) -> None:
    tenant_id = f"v2-eod-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await db_session.execute(
        text("UPDATE docintel.documents SET processing_status='RETRY_PENDING', confirmation_status='PENDING' "
             "WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    assert await beat._insert_eod_retry_jobs(db_session, tenant_id, datetime.now(UTC)) == 0


# ── status listing: what failed and what happens next ──────────────────────────

def test_listing_a_reading_waiting_on_its_daytime_retry() -> None:
    due = datetime(2026, 10, 20, 12, 10, tzinfo=UTC)
    status = retry_status({
        "state": "CLASSIFIED", "processing_status": "RETRY_PENDING", "upload_status": "FIT",
        "processing_failure_code": "DOCUMENT_AI_RESPONSE_INVALID", "processing_next_due_at_utc": due,
        "processing_attempts": 1,
    })
    assert status == {"scanPassed": True, "failureKind": "AI", "retryFailureCode": "DOCUMENT_AI_RESPONSE_INVALID",
                      "nextAttemptAtUtc": due, "inNightAttempt": False, "retryTonight": False, "attemptsMade": 1}


def test_listing_a_failed_reading() -> None:
    """2026-10-22: nothing is left for the night, not even a page our setup
    refused: a failed reading is final and the PC resubmits it."""
    row = {"state": "CLASSIFIED", "processing_status": "FAILED", "upload_status": "FIT",
           "processing_failure_code": "DOCUMENT_AI_UNAVAILABLE", "processing_attempts": 3}
    assert (retry_status(row)["retryTonight"], retry_status(row)["attemptsMade"]) == (False, 3)
    setup = {**row, "processing_failure_code": "DOCUMENT_AI_NOT_CONFIGURED", "processing_attempts": 1}
    assert retry_status(setup)["failureKind"] == "CONFIGURATION"
    assert (retry_status(setup)["retryTonight"], retry_status(setup)["inNightAttempt"]) == (False, False)
    assert retry_status(setup)["nextAttemptAtUtc"] is None
    technical = retry_status({**row, "processing_failure_code": "STORAGE_READ_ERROR"})
    assert (technical["failureKind"], technical["retryTonight"]) == ("TECHNICAL", False)


def test_listing_a_classification_retry_and_its_failures() -> None:
    due = datetime(2026, 10, 20, 12, 20, tzinfo=UTC)
    waiting = retry_status({
        "state": "STORED", "upload_status": "FIT", "classification_job_status": "PENDING",
        "classification_attempt_no": 2, "classification_error_code": "DOCUMENT_AI_RATE_LIMITED",
        "classification_due_at_utc": due,
    })
    assert (waiting["failureKind"], waiting["nextAttemptAtUtc"], waiting["attemptsMade"]) == ("AI", due, 2)
    first_try = retry_status({"state": "STORED", "upload_status": None, "classification_job_status": "PENDING",
                              "classification_attempt_no": 1})
    assert first_try["failureKind"] is None and first_try["scanPassed"] is None

    failed = {"state": "FAILED", "upload_status": "FIT", "failure_code": "DOCUMENT_AI_UNAVAILABLE",
              "classification_attempt_no": 3, "classification_job_status": "FAILED"}
    assert (retry_status(failed)["retryTonight"], retry_status(failed)["attemptsMade"]) == (False, 3)
    # A page our setup refused is final too (2026-10-22): no night re-read.
    setup = {**failed, "failure_code": "DOCUMENT_AI_NOT_CONFIGURED", "classification_attempt_no": 1}
    assert (retry_status(setup)["retryTonight"], retry_status(setup)["inNightAttempt"]) == (False, False)
    assert retry_status(setup)["failureKind"] == "CONFIGURATION"
    rejected = retry_status({"state": "FAILED", "upload_status": "NOT_FIT",
                             "failure_code": "DI_QUALITY_IMAGE_BLUR_SCORE"})
    assert (rejected["scanPassed"], rejected["failureKind"], rejected["retryTonight"]) == (False, "DOCUMENT", False)


@pytest.mark.asyncio
async def test_the_listing_query_carries_the_retry_fields(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib
    from collections.abc import AsyncIterator

    from verigence.di.api.v2 import capture_documents

    tenant_id = f"v2-list-{uuid.uuid4().hex[:8]}"
    document_id = await _v2_page_failed_reading(db_session, tenant_id, "DOCUMENT_AI_NOT_CONFIGURED")
    context_ref = (await db_session.execute(
        text("SELECT external_context_ref FROM docintel.document_capture_v2_uploads "
             "WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )).scalar_one()

    @contextlib.asynccontextmanager
    async def same_session(_tenant_id: str) -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(capture_documents, "tenant_session", same_session)
    [row] = await capture_documents._status_rows(tenant_id, context_ref, None)
    fields = capture_documents._retry_fields(row)
    assert fields == {"scanPassed": True, "failureKind": "CONFIGURATION",
                      "processingFailureCode": "DOCUMENT_AI_NOT_CONFIGURED", "nextAttemptAtUtc": None,
                      "inNightAttempt": False, "retryTonight": False, "attemptsMade": 3}
    # The response still carries the two night fields (Audit Core reads the
    # same shape before and after this change) and they are never true.
    assert "processing_next_job_type" not in row and "night_reprocess_used" not in row


def test_a_refused_key_or_model_is_final_and_is_not_read_again_at_night() -> None:
    """Gemini 401/403/404 is our configuration, not the page's: no daytime
    retries (2026-10-20) and, since 2026-10-22, no night re-read either. The
    page fails at once and the PC resubmits it once the setup is fixed."""
    from verigence.di.retry_policy import retry_delay_seconds

    assert retry_delay_seconds("DOCUMENT_AI_NOT_CONFIGURED", retryable=False, attempt_no=1) is None
    assert retry_delay_seconds("DOCUMENT_AI_NOT_CONFIGURED", retryable=True, attempt_no=1) is None


@pytest.mark.asyncio
async def test_a_v2_job_whose_worker_dies_runs_at_most_twice(db_session: AsyncSession) -> None:
    """A lease expiry is a technical failure: a Capture V2 job is reclaimed
    once, and the next expiry fails it (no third run)."""
    tenant_id = f"v2-lease-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    job_id = await _job(db_session, tenant_id, document_id, job_type="INITIAL", attempt_no=1, status="RUNNING",
                        locked_minutes_ago=60)

    async def job_state() -> tuple[Any, ...]:
        return tuple((await db_session.execute(
            text("SELECT job_status, lease_reclaim_count FROM docintel.processing_jobs "
                 "WHERE tenant_id=:t AND processing_job_id=:j"),
            {"t": tenant_id, "j": job_id},
        )).one())

    await beat._reclaim_stale_jobs(db_session, datetime.now(UTC))
    assert await job_state() == ("PENDING", 1)
    await db_session.execute(
        text("UPDATE docintel.processing_jobs SET job_status='RUNNING', locked_by='dead', "
             "locked_at_utc=now() - interval '1 hour' WHERE tenant_id=:t AND processing_job_id=:j"),
        {"t": tenant_id, "j": job_id},
    )
    await beat._reclaim_stale_jobs(db_session, datetime.now(UTC))
    assert await job_state() == ("FAILED", 1)


def test_classification_and_reading_share_one_budget_of_three_attempts() -> None:
    """2026-10-21 review: a page identified on its second attempt (T0+10)
    reads as attempt 2 of the budget, so it gets one reading retry (T0+20),
    never a fresh T0/+10/+20 of its own."""
    from verigence.di.retry_policy import budget_attempt, retry_delay_seconds

    code = "DOCUMENT_AI_UNAVAILABLE"
    assert budget_attempt(1, 1) == 1 and budget_attempt(1, None) == 1
    assert budget_attempt(1, 2) == 2  # identified at T0+10, first reading
    assert retry_delay_seconds(code, retryable=True, attempt_no=budget_attempt(1, 2)) == 600  # read again T0+20
    assert retry_delay_seconds(code, retryable=True, attempt_no=budget_attempt(2, 2)) is None  # then FAILED
    assert retry_delay_seconds(code, retryable=True, attempt_no=budget_attempt(1, 3)) is None  # identified at T0+20


@pytest.mark.asyncio
async def test_the_listing_counts_attempts_across_the_budget(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib
    from collections.abc import AsyncIterator

    from verigence.di.api.v2 import capture_documents

    tenant_id = f"v2-made-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    # identified on attempt 2 (T0+10); read at T0+10 and T0+20, both failed
    await db_session.execute(
        text("INSERT INTO docintel.document_capture_v2_classification_jobs "
             "(tenant_id, document_id, job_status, attempt_no) VALUES (:t, :d, 'COMPLETED', 2)"),
        {"t": tenant_id, "d": document_id},
    )
    await _job(db_session, tenant_id, document_id, job_type="INITIAL", attempt_no=1, status="FAILED")
    await _job(db_session, tenant_id, document_id, job_type="V2_FAST_RETRY", attempt_no=2, status="FAILED")
    await db_session.execute(
        text("UPDATE docintel.documents SET processing_status='FAILED', confirmation_status='NOT_CONFIRMED', "
             "processing_failure_code='DOCUMENT_AI_UNAVAILABLE' WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    context_ref = (await db_session.execute(
        text("SELECT external_context_ref FROM docintel.document_capture_v2_uploads "
             "WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )).scalar_one()

    @contextlib.asynccontextmanager
    async def same_session(_tenant_id: str) -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(capture_documents, "tenant_session", same_session)
    [row] = await capture_documents._status_rows(tenant_id, context_ref, None)
    assert capture_documents._retry_fields(row)["attemptsMade"] == 3

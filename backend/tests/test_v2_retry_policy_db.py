"""Product owner's retry rule (2026-10-20) against the real schema: a Capture
V2 page whose AI reading failed gets a second daytime retry (attempt 3) and
one night attempt, for classification and for reading; a technical failure
gets no night attempt; the EOD scheduler never stacks a retry on a V2 page;
the status listing says what failed and what happens next.

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
from verigence.di.repositories.processing_jobs import (
    insert_nightly_classification_retries,
    insert_nightly_reprocessing_jobs,
    schedule_v2_fast_retry,
)
from verigence.di.retry_policy import CLASSIFICATION_NIGHT_ATTEMPT_NO, retry_status
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
async def test_an_ai_reading_failure_gets_exactly_one_night_attempt(db_session: AsyncSession) -> None:
    tenant_id = f"v2-night-{uuid.uuid4().hex[:8]}"
    document_id = await _v2_page_failed_reading(db_session, tenant_id, "DOCUMENT_AI_UNAVAILABLE")

    assert await insert_nightly_reprocessing_jobs(db_session) == 1
    night = [tuple(j)[:3] for j in await _jobs_for(db_session, tenant_id, document_id)
             if j[0] == "NIGHTLY_REPROCESS"]
    assert night == [("NIGHTLY_REPROCESS", 3, "PENDING")]

    # The night attempt fails; a later night does not try again (legacy
    # documents would get up to three nights).
    await db_session.execute(
        text("UPDATE docintel.processing_jobs SET job_status='FAILED', created_at_utc=now() - interval '2 days' "
             "WHERE tenant_id=:t AND job_type='NIGHTLY_REPROCESS'"),
        {"t": tenant_id},
    )
    assert await insert_nightly_reprocessing_jobs(db_session) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["STORAGE_READ_ERROR", "WORKER_INTERNAL_ERROR", "DOCUMENT_AI_REQUEST_REJECTED"])
async def test_a_technical_or_refused_reading_gets_no_night_attempt(db_session: AsyncSession, code: str) -> None:
    tenant_id = f"v2-tech-{uuid.uuid4().hex[:8]}"
    await _v2_page_failed_reading(db_session, tenant_id, code)
    assert await insert_nightly_reprocessing_jobs(db_session) == 0


@pytest.mark.asyncio
async def test_an_ai_classification_failure_gets_one_night_attempt(db_session: AsyncSession) -> None:
    tenant_id = f"v2-cls-{uuid.uuid4().hex[:8]}"
    document_id = await _v2_page_failed_classification(db_session, tenant_id, "DOCUMENT_AI_RATE_LIMITED")

    assert await insert_nightly_classification_retries(db_session) == 1
    assert await _classification(db_session, tenant_id, document_id) == (
        "PENDING", CLASSIFICATION_NIGHT_ATTEMPT_NO, "STORED",
    )
    # Once the night attempt has failed too, it is never queued again.
    await db_session.execute(
        text("UPDATE docintel.document_capture_v2_classification_jobs SET job_status='FAILED' "
             "WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    await db_session.execute(
        text("UPDATE docintel.document_capture_v2_uploads SET state='FAILED' WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    assert await insert_nightly_classification_retries(db_session) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "upload_status"),
    [("CLASSIFICATION_FAILED", "FIT"), ("INVALID_FILE_CONTENT", "CORRUPT"),
     ("DOCUMENT_AI_UNAVAILABLE", "VALIDATING")],
)
async def test_no_night_classification_without_an_ai_failure_on_a_scanned_page(
    db_session: AsyncSession, code: str, upload_status: str,
) -> None:
    tenant_id = f"v2-clsno-{uuid.uuid4().hex[:8]}"
    await _v2_page_failed_classification(db_session, tenant_id, code, upload_status=upload_status)
    assert await insert_nightly_classification_retries(db_session) == 0


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
    })
    assert status == {"scanPassed": True, "failureKind": "AI", "retryFailureCode": "DOCUMENT_AI_RESPONSE_INVALID",
                      "nextAttemptAtUtc": due, "retryTonight": False}


def test_listing_a_failed_reading_left_for_the_night() -> None:
    row = {"state": "CLASSIFIED", "processing_status": "FAILED", "upload_status": "FIT",
           "processing_failure_code": "DOCUMENT_AI_UNAVAILABLE", "night_reprocess_used": False}
    assert retry_status(row)["retryTonight"] is True
    assert retry_status({**row, "night_reprocess_used": True})["retryTonight"] is False
    technical = retry_status({**row, "processing_failure_code": "STORAGE_READ_ERROR"})
    assert (technical["failureKind"], technical["retryTonight"]) == ("TECHNICAL", False)


def test_listing_a_classification_retry_and_its_failures() -> None:
    due = datetime(2026, 10, 20, 12, 20, tzinfo=UTC)
    waiting = retry_status({
        "state": "STORED", "upload_status": "FIT", "classification_job_status": "PENDING",
        "classification_attempt_no": 2, "classification_error_code": "DOCUMENT_AI_RATE_LIMITED",
        "classification_due_at_utc": due,
    })
    assert (waiting["failureKind"], waiting["nextAttemptAtUtc"]) == ("AI", due)
    first_try = retry_status({"state": "STORED", "upload_status": None, "classification_job_status": "PENDING",
                              "classification_attempt_no": 1})
    assert first_try["failureKind"] is None and first_try["scanPassed"] is None

    failed = {"state": "FAILED", "upload_status": "FIT", "failure_code": "DOCUMENT_AI_UNAVAILABLE",
              "classification_attempt_no": 3}
    assert retry_status(failed)["retryTonight"] is True
    assert retry_status({**failed, "classification_attempt_no": CLASSIFICATION_NIGHT_ATTEMPT_NO})["retryTonight"] is False
    # an AI failure on a page that never passed the scan is not left for the night
    assert retry_status({**failed, "upload_status": "VALIDATING"})["retryTonight"] is False
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
    document_id = await _v2_page_failed_reading(db_session, tenant_id, "DOCUMENT_AI_UNAVAILABLE")
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
    assert fields == {"scanPassed": True, "failureKind": "AI", "processingFailureCode": "DOCUMENT_AI_UNAVAILABLE",
                      "nextAttemptAtUtc": None, "retryTonight": True}

    await _job(db_session, tenant_id, document_id, job_type="NIGHTLY_REPROCESS", attempt_no=4, status="FAILED")
    [row] = await capture_documents._status_rows(tenant_id, context_ref, None)
    assert capture_documents._retry_fields(row)["retryTonight"] is False

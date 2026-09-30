"""tests/test_nightly_once_and_reaper.py

Nightly Reprocessing runs at most once per document per night, skips business
failures and keeps the original correlation id; the daily run marker is
claimed once; the stale-job reapers bound retries of a job whose worker keeps
dying, for both processing and Capture V2 classification jobs.

Every test runs inside the db_session transaction, which is rolled back.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import RetentionDisposition, SubjectType
from verigence.di.repositories.audit_storage_contexts import ensure_audit_storage_context
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.documents import create_document_receiving
from verigence.di.repositories.processing_jobs import insert_nightly_reprocessing_jobs
from verigence.di.repositories.scheduler_runs import claim_scheduler_run
from verigence.di.repositories.subjects import create_subject
from verigence.di.repositories.tenants import (
    provision_actor,
    provision_retention_policy,
    provision_tenant,
    provision_tenant_document_types,
)
from verigence.di.scheduler import beat
from verigence.di.workers.capture_v2_classifier import CLASSIFICATION_MAX_ATTEMPTS


class _Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def bind(self, **_: Any) -> _Log:
        return self

    def __getattr__(self, level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **kwargs: Any) -> None:
            self.events.append((level, event, kwargs))
        return record


async def _failed_document(
    session: AsyncSession, tenant_id: str, *, failure_code: str, initial_correlation: str,
) -> uuid.UUID:
    await set_tenant_context(session, tenant_id)
    await provision_tenant(session, tenant_id)
    policy_id = await provision_retention_policy(session, tenant_id)
    await provision_actor(session, tenant_id, "test-uploader", "USER")
    document_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO docintel.documents (
                tenant_id, document_id, active_retention_policy_id, upload_status,
                retention_disposition, source_channel, uploaded_by_actor_type, uploaded_by_actor_id,
                registered_at_utc, correlation_id, created_at_utc, updated_at_utc
            ) VALUES (:t, :d, :p, 'FIT', 'PURGE_CONTENT', 'WEB', 'USER', 'test-uploader',
                      now(), 'doc-correlation', now(), now())
            """
        ),
        {"t": tenant_id, "d": document_id, "p": policy_id},
    )
    await session.execute(
        text(
            """
            UPDATE docintel.documents
            SET processing_status='FAILED', confirmation_status='NOT_CONFIRMED',
                processing_failure_code=:code
            WHERE tenant_id=:t AND document_id=:d
            """
        ),
        {"t": tenant_id, "d": document_id, "code": failure_code},
    )
    await _job(session, tenant_id, document_id, job_type="INITIAL", attempt_no=1,
               status="FAILED", correlation_id=initial_correlation)
    return document_id


async def _job(
    session: AsyncSession, tenant_id: str, document_id: uuid.UUID, *, job_type: str, attempt_no: int,
    status: str, correlation_id: str = "test", locked_minutes_ago: int | None = None,
    lease_reclaim_count: int = 0,
) -> uuid.UUID:
    job_id = uuid.uuid4()
    locked_at = (
        datetime.now(UTC) - timedelta(minutes=locked_minutes_ago)
        if locked_minutes_ago is not None else None
    )
    await session.execute(
        text(
            """
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id, job_type, job_status,
                 due_at_utc, attempt_no, created_at_utc, locked_by, locked_at_utc, lease_reclaim_count)
            VALUES (:t, :j, :d, :c, :type, :s, now(), :a, now(), :locked_by, :locked_at, :reclaims)
            """
        ),
        {"t": tenant_id, "j": job_id, "d": document_id, "c": correlation_id, "type": job_type,
         "s": status, "a": attempt_no, "locked_by": "dead-worker" if locked_at else None,
         "locked_at": locked_at, "reclaims": lease_reclaim_count},
    )
    return job_id


async def _nightly_jobs(session: AsyncSession, tenant_id: str) -> list[Any]:
    return list(
        (
            await session.execute(
                text(
                    "SELECT attempt_no, correlation_id, job_status FROM docintel.processing_jobs "
                    "WHERE tenant_id=:t AND job_type='NIGHTLY_REPROCESS' ORDER BY attempt_no"
                ),
                {"t": tenant_id},
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_a_quickly_failing_nightly_attempt_is_not_requeued_the_same_night(
    db_session: AsyncSession,
) -> None:
    tenant_id = f"nightly-once-{uuid.uuid4().hex[:10]}"
    await _failed_document(db_session, tenant_id, failure_code="DOCUMENT_AI_UNAVAILABLE",
                           initial_correlation="audit-core-request-1")

    await insert_nightly_reprocessing_jobs(db_session)
    jobs = await _nightly_jobs(db_session, tenant_id)
    assert [(j[0], j[1]) for j in jobs] == [(3, "audit-core-request-1")]

    # The attempt fails within seconds; the next tick is still inside the window.
    await db_session.execute(
        text("UPDATE docintel.processing_jobs SET job_status='FAILED' "
             "WHERE tenant_id=:t AND job_type='NIGHTLY_REPROCESS'"),
        {"t": tenant_id},
    )
    await insert_nightly_reprocessing_jobs(db_session)
    assert len(await _nightly_jobs(db_session, tenant_id)) == 1


@pytest.mark.asyncio
async def test_the_next_night_still_gets_its_attempt(db_session: AsyncSession) -> None:
    tenant_id = f"nightly-next-{uuid.uuid4().hex[:10]}"
    document_id = await _failed_document(db_session, tenant_id, failure_code="WORKER_INTERNAL_ERROR",
                                         initial_correlation="audit-core-request-2")
    last_night = await _job(db_session, tenant_id, document_id, job_type="NIGHTLY_REPROCESS",
                            attempt_no=3, status="FAILED")
    await db_session.execute(
        text("UPDATE docintel.processing_jobs SET created_at_utc = now() - interval '1 day' "
             "WHERE tenant_id=:t AND processing_job_id=:j"),
        {"t": tenant_id, "j": last_night},
    )

    await insert_nightly_reprocessing_jobs(db_session)

    assert [j[0] for j in await _nightly_jobs(db_session, tenant_id)] == [3, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_code",
    ["CLASSIFICATION_AMBIGUOUS", "CLASSIFICATION_NO_CANDIDATES", "EXTRACTION_PROFILE_EMPTY",
     "INVALID_FILE_CONTENT", "DOCUMENT_AI_CONTENT_BLOCKED", "WORKER_LEASE_EXHAUSTED"],
)
async def test_business_and_configuration_failures_are_not_reprocessed(
    db_session: AsyncSession, failure_code: str,
) -> None:
    tenant_id = f"nightly-biz-{uuid.uuid4().hex[:10]}"
    await _failed_document(db_session, tenant_id, failure_code=failure_code,
                           initial_correlation="audit-core-request-3")

    await insert_nightly_reprocessing_jobs(db_session)

    assert await _nightly_jobs(db_session, tenant_id) == []


@pytest.mark.asyncio
async def test_the_daily_run_marker_is_claimed_once(db_session: AsyncSession) -> None:
    run_date = date(2000, 1, 1) + timedelta(days=uuid.uuid4().int % 10000)
    now = datetime.now(UTC)
    run_name = f"TEST_{uuid.uuid4().hex[:8]}"
    first = await claim_scheduler_run(db_session, run_name=run_name, run_date=run_date,
                                      claimed_by="replica-a", now=now)
    second = await claim_scheduler_run(db_session, run_name=run_name, run_date=run_date,
                                       claimed_by="replica-b", now=now)
    assert (first, second) == (True, False)


@pytest.mark.asyncio
async def test_reaper_resets_then_abandons_a_job_whose_worker_keeps_dying(
    db_session: AsyncSession,
) -> None:
    tenant_id = f"reaper-{uuid.uuid4().hex[:10]}"
    document_id = await _failed_document(db_session, tenant_id, failure_code="WORKER_INTERNAL_ERROR",
                                         initial_correlation="audit-core-request-4")
    await db_session.execute(
        text("UPDATE docintel.documents SET processing_status='RETRY_PENDING', "
             "confirmation_status='PENDING' WHERE tenant_id=:t"),
        {"t": tenant_id},
    )
    fresh = await _job(db_session, tenant_id, document_id, job_type="EOD_RETRY", attempt_no=2,
                       status="RUNNING", locked_minutes_ago=60)
    log = _Log()

    await beat._reclaim_stale_jobs(db_session, datetime.now(UTC), log=log)
    row = (await db_session.execute(
        text("SELECT job_status, lease_reclaim_count, locked_by FROM docintel.processing_jobs "
             "WHERE tenant_id=:t AND processing_job_id=:j"), {"t": tenant_id, "j": fresh},
    )).one()
    assert tuple(row) == ("PENDING", 1, None)
    reset = [e for e in log.events if e[1] == "stale_running_job_reset"]
    assert reset and str(fresh) in reset[0][2]["processing_job_ids"]

    # Claimed again and the worker died again, past the reclaim budget.
    await db_session.execute(
        text("UPDATE docintel.processing_jobs SET job_status='RUNNING', lease_reclaim_count=2, "
             "locked_at_utc=now() - interval '1 hour' WHERE tenant_id=:t AND processing_job_id=:j"),
        {"t": tenant_id, "j": fresh},
    )
    await beat._reclaim_stale_jobs(db_session, datetime.now(UTC), log=log)

    job = (await db_session.execute(
        text("SELECT job_status, error_code FROM docintel.processing_jobs "
             "WHERE tenant_id=:t AND processing_job_id=:j"), {"t": tenant_id, "j": fresh},
    )).one()
    document = (await db_session.execute(
        text("SELECT processing_status, processing_failure_code FROM docintel.documents "
             "WHERE tenant_id=:t"), {"t": tenant_id},
    )).one()
    backout = (await db_session.execute(
        text("SELECT error_code, error_class FROM docintel.backout_jobs WHERE tenant_id=:t"),
        {"t": tenant_id},
    )).one()
    assert tuple(job) == ("FAILED", "WORKER_LEASE_EXHAUSTED")
    assert tuple(document) == ("FAILED", "WORKER_LEASE_EXHAUSTED")
    assert tuple(backout) == ("WORKER_LEASE_EXHAUSTED", "NON_RETRYABLE")
    abandoned = [e for e in log.events if e[1] == "stale_running_job_abandoned"]
    assert abandoned and abandoned[0][0] == "error"
    assert str(fresh) in abandoned[0][2]["processing_job_ids"]


async def _classifying_upload(session: AsyncSession, tenant_id: str, *, attempt_no: int) -> uuid.UUID:
    await set_tenant_context(session, tenant_id)
    await provision_tenant(session, tenant_id)
    retention_policy_id = await provision_retention_policy(session, tenant_id)
    await provision_tenant_document_types(session, tenant_id)
    subject = await create_subject(
        session, tenant_id=tenant_id, subject_type=SubjectType.PERSON,
        display_name="Reaper Subject", created_by_actor_id="test-actor",
    )
    document = await create_document_receiving(
        session, tenant_id=tenant_id, subject_id=subject["subject_id"],
        uploaded_by_actor_id="test-actor", uploaded_by_actor_type="USER",
        correlation_id=str(uuid.uuid4()), retention_policy_id=retention_policy_id,
        retention_days=365, retention_disposition=RetentionDisposition.PURGE_CONTENT,
    )
    document_id: uuid.UUID = document["document_id"]
    context = await ensure_audit_storage_context(
        session, tenant_id=tenant_id, external_context_ref=f"ctx-{uuid.uuid4()}",
        dealer_id=uuid.uuid4(), dealer_outlet_id=uuid.uuid4(), customer_id=uuid.uuid4(),
        subject_id=subject["subject_id"], service_principal_id="test-service",
        project_slug="proj", dealer_slug="dlr", dealer_outlet_slug="out", customer_slug="cust",
    )
    await session.execute(
        text(
            """
            INSERT INTO docintel.document_capture_v2_uploads (
                tenant_id, document_id, audit_storage_context_id, external_context_ref, phase,
                client_upload_id, logical_object_key, original_filename, declared_mime_type,
                candidate_document_type_keys, state, created_at_utc, updated_at_utc
            ) VALUES (
                :t, :d, :ctx, :ref, 'BOOKING', :client, :key, 'a.pdf', 'application/pdf',
                CAST('["booking_form"]' AS jsonb), 'CLASSIFYING', now(), now()
            )
            """
        ),
        {"t": tenant_id, "d": document_id, "ctx": context["storage_context_id"],
         "ref": context["external_context_ref"], "client": f"upload-{uuid.uuid4()}",
         "key": f"{tenant_id}/{document_id}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO docintel.document_capture_v2_classification_jobs
                (tenant_id, document_id, job_status, attempt_no, locked_by, locked_at_utc)
            VALUES (:t, :d, 'RUNNING', :a, 'dead-worker', now() - interval '1 hour')
            """
        ),
        {"t": tenant_id, "d": document_id, "a": attempt_no},
    )
    return document_id


async def _classification_state(session: AsyncSession, tenant_id: str) -> tuple[Any, ...]:
    row = (await session.execute(
        text(
            """
            SELECT j.job_status, j.attempt_no, j.locked_by, u.state, u.failure_code
            FROM docintel.document_capture_v2_classification_jobs j
            JOIN docintel.document_capture_v2_uploads u
              ON u.tenant_id=j.tenant_id AND u.document_id=j.document_id
            WHERE j.tenant_id=:t
            """
        ),
        {"t": tenant_id},
    )).one()
    return tuple(row)


@pytest.mark.asyncio
async def test_stale_classification_job_gets_another_attempt(db_session: AsyncSession) -> None:
    tenant_id = f"reaper-v2-{uuid.uuid4().hex[:10]}"
    await _classifying_upload(db_session, tenant_id, attempt_no=1)
    log = _Log()

    await beat._reclaim_stale_classification_jobs(db_session, datetime.now(UTC), log=log)

    assert await _classification_state(db_session, tenant_id) == ("PENDING", 2, None, "STORED", None)
    assert any(e[1] == "stale_classification_job_reset" for e in log.events)


@pytest.mark.asyncio
async def test_stale_classification_job_out_of_attempts_fails_the_upload(db_session: AsyncSession) -> None:
    tenant_id = f"reaper-v2-{uuid.uuid4().hex[:10]}"
    # The last allowed attempt (five since the retry ladder of 2026-09-30).
    await _classifying_upload(db_session, tenant_id, attempt_no=CLASSIFICATION_MAX_ATTEMPTS)
    log = _Log()

    await beat._reclaim_stale_classification_jobs(db_session, datetime.now(UTC), log=log)

    assert await _classification_state(db_session, tenant_id) == (
        "FAILED", CLASSIFICATION_MAX_ATTEMPTS, None, "FAILED", "CLASSIFICATION_FAILED",
    )
    failed = [e for e in log.events if e[1] == "stale_classification_job_failed"]
    assert failed and failed[0][0] == "error"

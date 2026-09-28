"""tests/test_nightly_reprocess_superseded.py

Regression for a live loop (DEV, 2026-09-28): two NIGHTLY_REPROCESS jobs were
queued for a document that another attempt then PROCESSED. Each job's Step 3
put the CONFIRMED document back into PROCESSING -- violating
ck_documents_confirmation_invariants -- and recording that failure violated it
again (fail_job set FAILED next to the confirmed attempt's scores), so the job
stayed RUNNING. The stale-job reaper reset it every lease period and the pair
failed again, forever.

Now: a retry/reprocess job for an already-PROCESSED document is CANCELLED as
superseded without touching the document; fail_job never demotes a PROCESSED
document; a nightly job is never queued alongside a pending/running one; and a
failure handler that itself fails still closes the job.
"""
from __future__ import annotations

import inspect
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.document_ai.adapter import get_document_ai_adapter
from verigence.di.document_ai.v2_preclassified_adapter import V2PreclassifiedAdapter
from verigence.di.repositories import processing_jobs
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.processing_jobs import fail_job, insert_nightly_reprocessing_jobs
from verigence.di.repositories.tenants import (
    provision_actor,
    provision_retention_policy,
    provision_tenant,
)
from verigence.di.workers import processor


async def _document(session: AsyncSession, tenant_id: str, *, processed: bool) -> uuid.UUID:
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
                      now(), 'test', now(), now())
            """
        ),
        {"t": tenant_id, "d": document_id, "p": policy_id},
    )
    if processed:
        await session.execute(
            text(
                """
                UPDATE docintel.documents
                SET processing_status='PROCESSED', confirmation_status='CONFIRMED',
                    confidence_score=95, verification_threshold_applied=90,
                    human_verification_status='OPTIONAL'
                WHERE tenant_id=:t AND document_id=:d
                """
            ),
            {"t": tenant_id, "d": document_id},
        )
    else:
        await session.execute(
            text(
                "UPDATE docintel.documents SET processing_status='FAILED', confirmation_status='NOT_CONFIRMED' "
                "WHERE tenant_id=:t AND document_id=:d"
            ),
            {"t": tenant_id, "d": document_id},
        )
    return document_id


async def _job(session: AsyncSession, tenant_id: str, document_id: uuid.UUID, *, attempt_no: int,
               status: str) -> uuid.UUID:
    job_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO docintel.processing_jobs
                (tenant_id, processing_job_id, document_id, correlation_id,
                 job_type, job_status, due_at_utc, attempt_no, created_at_utc)
            VALUES (:t, :j, :d, :c, 'NIGHTLY_REPROCESS', :s, now(), :a, now())
            """
        ),
        {"t": tenant_id, "j": job_id, "d": document_id, "c": f"nightly.{uuid.uuid4()}",
         "s": status, "a": attempt_no},
    )
    return job_id


class _Log:
    def __init__(self) -> None:
        self.events: list[str] = []

    def bind(self, **_: Any) -> _Log:
        return self

    def __getattr__(self, _level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **_: Any) -> None:
            self.events.append(event)
        return record


@pytest.mark.asyncio
async def test_reprocessing_an_already_processed_document_is_cancelled_not_looped(db_url: str) -> None:
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = f"superseded-{uuid.uuid4().hex[:10]}"
    try:
        async with factory() as session, session.begin():
            document_id = await _document(session, tenant_id, processed=True)
            jobs = [await _job(session, tenant_id, document_id, attempt_no=n, status="RUNNING") for n in (3, 4)]

        adapter = V2PreclassifiedAdapter(get_document_ai_adapter(), document_type_key="credit_note",
                                         confidence=Decimal("100"))
        log = _Log()
        for job_id, attempt in zip(jobs, (3, 4), strict=True):
            await processor._execute_claimed_job(
                session_factory=factory,
                job={"tenant_id": tenant_id, "processing_job_id": job_id, "document_id": document_id,
                     "correlation_id": "nightly.test", "job_type": "NIGHTLY_REPROCESS", "attempt_no": attempt,
                     "capture_v2_document_type_key": "credit_note", "capture_v2_classification_confidence": 100},
                ai_adapter=adapter,
                log=log,
            )

        async with factory() as session, session.begin():
            await set_tenant_context(session, tenant_id)
            statuses = (await session.execute(
                text("SELECT job_status, error_code FROM docintel.processing_jobs WHERE tenant_id=:t"),
                {"t": tenant_id},
            )).all()
            document = (await session.execute(
                text("SELECT processing_status, confirmation_status, confidence_score FROM docintel.documents "
                     "WHERE tenant_id=:t"), {"t": tenant_id},
            )).one()
        assert {tuple(s) for s in statuses} == {("CANCELLED", "SUPERSEDED_ALREADY_PROCESSED")}
        assert (document[0], document[1]) == ("PROCESSED", "CONFIRMED") and document[2] is not None
        assert log.events.count("job_superseded") == 2
        assert "job_runner_unexpected_escape" not in log.events
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fail_job_never_demotes_a_processed_document(db_session: AsyncSession) -> None:
    tenant_id = f"superseded-{uuid.uuid4().hex[:10]}"
    document_id = await _document(db_session, tenant_id, processed=True)
    job_id = await _job(db_session, tenant_id, document_id, attempt_no=3, status="RUNNING")
    await fail_job(db_session, tenant_id=tenant_id, processing_job_id=job_id, document_id=document_id,
                   error_code="X", error_detail="x")  # must not raise ck_documents_confirmation_invariants
    row = (await db_session.execute(
        text("SELECT processing_status, confirmation_status FROM docintel.documents WHERE tenant_id=:t"),
        {"t": tenant_id},
    )).one()
    assert tuple(row) == ("PROCESSED", "CONFIRMED")


@pytest.mark.asyncio
async def test_no_nightly_job_is_queued_beside_one_still_pending(db_session: AsyncSession) -> None:
    tenant_id = f"superseded-{uuid.uuid4().hex[:10]}"
    document_id = await _document(db_session, tenant_id, processed=False)
    await _job(db_session, tenant_id, document_id, attempt_no=3, status="PENDING")
    await insert_nightly_reprocessing_jobs(db_session)
    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM docintel.processing_jobs WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )).scalar_one()
    assert count == 1


@pytest.mark.no_docker
@pytest.mark.asyncio
async def test_a_failure_handler_that_fails_still_closes_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken_handler(**_: Any) -> None:
        raise RuntimeError("check constraint violated while recording the failure")

    closed: list[dict[str, Any]] = []

    async def close(_session: Any, **kwargs: Any) -> None:
        closed.append(kwargs)

    monkeypatch.setattr(processor, "_handle_failure", broken_handler)
    monkeypatch.setattr(processor, "close_job_after_handler_error", close)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value = session
    job_id = uuid.uuid4()
    await processor._handle_failure_safely(
        session_factory=lambda: session, tenant_id="t", job_id=job_id, document_id=uuid.uuid4(),
        correlation_id="c", processing_run_id=None, error_code="DATABASE_UNAVAILABLE", error_detail=None,
        retryable=True, attempt_no=3, is_capture_v2=True, job_log=_Log(),
    )
    assert closed == [{"tenant_id": "t", "processing_job_id": job_id, "error_code": "DATABASE_UNAVAILABLE"}]


@pytest.mark.no_docker
def test_fail_job_sql_guards_processed_documents() -> None:
    source = inspect.getsource(processing_jobs.fail_job)
    assert "processing_status <> 'PROCESSED'" in source
    nightly = inspect.getsource(processing_jobs.insert_nightly_reprocessing_jobs)
    assert "job_status IN ('PENDING', 'RUNNING')" in nightly

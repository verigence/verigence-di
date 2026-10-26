"""tests/test_forced_reread.py

A document DI already read can be read once more on request (``force``): used
by Audit Core after a schema gained a field (customer_ledger 1.1 added the
printed net value, and the statements read before it have no such value).

What must hold, against real Postgres:
- without ``force`` a read document is still reported as already processed;
- ``force`` queues a MANUAL_REREAD, but not over a person's work (a verified
  document or a corrected value is refused as ``has_corrections``);
- the worker does not cancel that job as "superseded" (the document was
  PROCESSED before the job existed), yet still cancels one that another
  attempt made redundant after it was queued;
- the PROCESSING statement can take a PROCESSED document back (its scores and
  verification mark are cleared, as ck_documents_confirmation_invariants
  requires), and the earlier machine values stop being current.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_nightly_once_and_reaper import _classified_unqueued_upload, _jobs_for
from verigence.di.repositories.processing_jobs import job_superseded, request_manual_reread
from verigence.di.workers import job_runner


async def _processed(session: AsyncSession, tenant_id: str, document_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "UPDATE docintel.documents SET processing_status='PROCESSED', confirmation_status='CONFIRMED', "
            "confidence_score=95, verification_threshold_applied=90, human_verification_status='OPTIONAL' "
            "WHERE tenant_id=:t AND document_id=:d"
        ),
        {"t": tenant_id, "d": document_id},
    )


async def _first_attempt_completed(session: AsyncSession, tenant_id: str, document_id: uuid.UUID) -> None:
    first = await request_manual_reread(session, tenant_id=tenant_id, document_id=document_id, requested_by="svc")
    assert first["outcome"] == "queued"
    await session.execute(
        text("UPDATE docintel.processing_jobs SET job_status='COMPLETED' WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    await _processed(session, tenant_id, document_id)


@pytest.mark.asyncio
async def test_force_queues_a_second_reading_only_when_asked(db_session: AsyncSession) -> None:
    tenant_id = f"tenant-force-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await _first_attempt_completed(db_session, tenant_id, document_id)

    plain = await request_manual_reread(db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc")
    assert plain == {"outcome": "already_processed"}

    forced = await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    assert forced["outcome"] == "queued" and forced["jobType"] == "MANUAL_REREAD" and forced["attemptNo"] == 2
    again = await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    assert again == {"outcome": "in_progress"}
    assert [(j[0], j[1]) for j in await _jobs_for(db_session, tenant_id, document_id)] == [
        ("INITIAL", 1), ("MANUAL_REREAD", 2),
    ]


@pytest.mark.asyncio
async def test_force_never_replaces_a_persons_work(db_session: AsyncSession) -> None:
    tenant_id = f"tenant-force-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await _first_attempt_completed(db_session, tenant_id, document_id)

    await db_session.execute(
        text("UPDATE docintel.documents SET verification_state='VERIFIED' WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    verified = await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    assert verified == {"outcome": "has_corrections"}

    await db_session.execute(
        text("UPDATE docintel.documents SET verification_state='NOT_VERIFIED' WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )
    canonical_field_id = (await db_session.execute(text("SELECT canonical_field_id FROM docintel.canonical_fields LIMIT 1"))).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO docintel.document_field_values (tenant_id, document_field_value_id, document_id, "
            "canonical_field_id, current_value, value_source, accepted_by_actor_id, accepted_at_utc, version_no, "
            "is_current, created_at_utc) VALUES (:t, :v, :d, :c, CAST('\"x\"' AS jsonb), 'EXTERNAL', 'test-actor', now(), 2, true, now())"
        ),
        {"t": tenant_id, "v": uuid.uuid4(), "d": document_id, "c": canonical_field_id},
    )
    corrected = await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    assert corrected == {"outcome": "has_corrections"}
    assert len(await _jobs_for(db_session, tenant_id, document_id)) == 1


@pytest.mark.asyncio
async def test_worker_runs_a_forced_job_but_cancels_one_another_attempt_made_redundant(
    db_session: AsyncSession,
) -> None:
    tenant_id = f"tenant-force-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await _first_attempt_completed(db_session, tenant_id, document_id)
    # The document was last touched before the forced job is queued.
    await db_session.execute(
        text("UPDATE docintel.documents SET updated_at_utc = now() - interval '1 hour' WHERE tenant_id=:t"),
        {"t": tenant_id},
    )
    await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    job_id = (await db_session.execute(
        text("SELECT processing_job_id FROM docintel.processing_jobs WHERE tenant_id=:t AND job_type='MANUAL_REREAD'"),
        {"t": tenant_id},
    )).scalar_one()
    assert not await job_superseded(db_session, tenant_id=tenant_id, document_id=document_id, processing_job_id=job_id)

    # Another attempt PROCESSED the document after the job was queued.
    await db_session.execute(
        text("UPDATE docintel.documents SET updated_at_utc = now() + interval '1 minute' WHERE tenant_id=:t"),
        {"t": tenant_id},
    )
    assert await job_superseded(db_session, tenant_id=tenant_id, document_id=document_id, processing_job_id=job_id)


@pytest.mark.asyncio
async def test_processing_statement_takes_a_processed_document_back(db_session: AsyncSession) -> None:
    tenant_id = f"tenant-force-{uuid.uuid4().hex[:8]}"
    document_id = await _classified_unqueued_upload(db_session, tenant_id)
    await _first_attempt_completed(db_session, tenant_id, document_id)

    source = inspect.getsource(job_runner._execute_steps)
    start = source.index("UPDATE docintel.documents")
    statement = source[start:source.index('"""),', start)]
    forced = await request_manual_reread(
        db_session, tenant_id=tenant_id, document_id=document_id, requested_by="svc", force=True,
    )
    job_id = uuid.UUID(forced["processingJobId"])
    run_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO docintel.processing_runs (tenant_id, processing_run_id, processing_job_id, document_id, "
            "correlation_id, run_type, run_status, pipeline_version, started_at_utc, created_at_utc) "
            "VALUES (:t, :r, :j, :d, 'c', 'MANUAL_REREAD', 'RUNNING', 'test', now(), now())"
        ),
        {"t": tenant_id, "r": run_id, "j": job_id, "d": document_id},
    )
    await db_session.execute(
        text(statement), {"tid": tenant_id, "doc_id": document_id, "run_id": run_id, "now": datetime.now(UTC)},
    )
    row = (await db_session.execute(
        text("SELECT processing_status, confirmation_status, confidence_score, human_verification_status, "
             "verification_state FROM docintel.documents WHERE tenant_id=:t AND document_id=:d"),
        {"t": tenant_id, "d": document_id},
    )).one()
    assert tuple(row) == ("PROCESSING", "PENDING", None, None, "NOT_VERIFIED")


@pytest.mark.no_docker
def test_earlier_machine_values_are_retired_before_the_new_ones_are_inserted() -> None:
    source = inspect.getsource(job_runner._execute_steps)
    retire = source.index("SET is_current = false")
    insert = source.index("INSERT INTO docintel.document_field_values")
    assert retire < insert
    assert "value_source = 'MACHINE'" in source[retire - 200:retire + 300]

"""tests/test_nightly_reprocess_confirmation_invariant.py

Regression for job_runner.py's Step 3 (set Document PROCESSING) against real
Postgres. Confirmed live (2026-09-23): once migration 0044 let
NIGHTLY_REPROCESS jobs actually be inserted for the first time, every single
one of them still failed within milliseconds -- before any real extraction
work ran -- because Step 3's UPDATE only set processing_status='PROCESSING'
without also moving confirmation_status to 'PENDING'.
ck_documents_confirmation_invariants (0001_initial_schema.py) only allows
processing_status='PROCESSING' paired with confirmation_status='PENDING'; a
permanently-FAILED document sits at confirmation_status='NOT_CONFIRMED'
(fail_job()'s terminal state), and NIGHTLY_REPROCESS is the first thing that
ever re-attempts a document from that terminal state, so this branch was
never exercised until 0044 unblocked the insert itself.

INITIAL and EOD_RETRY/V2_FAST_RETRY jobs never hit this because their
documents already carry confirmation_status='PENDING' by the time Step 3
runs (set at document creation and by retry_job() respectively) -- this test
instead reproduces the un-exercised path: a document already at the
FAILED/NOT_CONFIRMED terminal state.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.tenants import provision_retention_policy, provision_tenant


async def _make_failed_document(db_session, tenant_id: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    policy_id = await provision_retention_policy(db_session, tenant_id)
    document_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.documents (
                tenant_id, document_id, active_retention_policy_id,
                upload_status, retention_disposition,
                source_channel, uploaded_by_actor_type, uploaded_by_actor_id,
                registered_at_utc, correlation_id, created_at_utc, updated_at_utc
            ) VALUES (
                :tenant_id, :document_id, :policy_id,
                'FIT', 'PURGE_CONTENT',
                'WEB', 'USER', 'test-uploader',
                now(), 'test-correlation', now(), now()
            )
            """
        ),
        {"tenant_id": tenant_id, "document_id": document_id, "policy_id": policy_id},
    )
    # Reach the exact terminal state fail_job() leaves a permanently-FAILED
    # document in -- the state every NIGHTLY_REPROCESS-eligible document is
    # actually found in by insert_nightly_reprocessing_jobs' own query.
    await db_session.execute(
        text(
            """
            UPDATE docintel.documents
            SET processing_status = 'FAILED', confirmation_status = 'NOT_CONFIRMED'
            WHERE tenant_id = :tenant_id AND document_id = :document_id
            """
        ),
        {"tenant_id": tenant_id, "document_id": document_id},
    )
    return document_id


@pytest.mark.asyncio
async def test_step_3_moves_a_permanently_failed_document_back_into_processing(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    tenant_id = f"nightly-invariant-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    await db_session.flush()

    document_id = await _make_failed_document(db_session, tenant_id)
    run_id = uuid.uuid4()

    # The exact statement job_runner.py's _execute_steps runs at Step 3 --
    # must not raise ck_documents_confirmation_invariants.
    await db_session.execute(
        text(
            """
            UPDATE docintel.documents
            SET processing_status = 'PROCESSING',
                confirmation_status = 'PENDING',
                current_processing_run_id = :run_id,
                updated_at_utc = now()
            WHERE tenant_id = :tenant_id AND document_id = :document_id
            """
        ),
        {"tenant_id": tenant_id, "document_id": document_id, "run_id": run_id},
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                """
                SELECT processing_status, confirmation_status, current_processing_run_id
                FROM docintel.documents
                WHERE tenant_id = :tenant_id AND document_id = :document_id
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id},
        )
    ).mappings().one()

    assert row["processing_status"] == "PROCESSING"
    assert row["confirmation_status"] == "PENDING"
    assert row["current_processing_run_id"] == run_id


@pytest.mark.no_docker
def test_job_runner_step_3_sql_sets_confirmation_status_pending() -> None:
    """Source-inspection guard: the exact UPDATE statement must set both
    columns together, not just processing_status -- a future edit that drops
    confirmation_status here would silently reintroduce the same
    CheckViolation for every NIGHTLY_REPROCESS attempt."""
    import inspect

    from verigence.di.workers import job_runner

    source = inspect.getsource(job_runner._execute_steps)
    # Scope strictly to Step 3's own statement (up to its closing `"""),`) so
    # a later step's unrelated UPDATE docintel.documents can't make this
    # assertion pass by accident.
    start = source.index("UPDATE docintel.documents")
    end = source.index('"""),', start)
    step_3 = source[start:end]
    assert "processing_status = 'PROCESSING'" in step_3
    assert "confirmation_status = 'PENDING'" in step_3

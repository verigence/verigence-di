"""tests/test_nightly_reprocessing_constraints.py

Regression for migration 0040. Confirms the constraint changes it makes
actually took effect against real Postgres -- not just that the migration
file contains the right SQL strings. Requires the real (Docker) Postgres
test database, matching test_processing_runs_run_type_constraint.py's
established pattern for this same kind of check.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_processing_jobs_unique_constraint_now_includes_attempt_no(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'processing_jobs_tenant_document_jobtype_attempt_key'"
            )
        )
    ).scalar_one()
    assert "tenant_id" in definition
    assert "document_id" in definition
    assert "job_type" in definition
    assert "attempt_no" in definition
    # The old 3-column constraint this replaces must be gone -- if both
    # existed, NIGHTLY_REPROCESS's multiple-rows-per-document design would
    # still be blocked by the narrower one.
    old_constraint_still_exists = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = 'processing_jobs_tenant_id_document_id_job_type_key'"
            )
        )
    ).scalar_one()
    assert old_constraint_still_exists == 0


@pytest.mark.asyncio
async def test_processing_jobs_job_type_check_allows_nightly_reprocess(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'processing_jobs_job_type_check'"
            )
        )
    ).scalar_one()
    assert "NIGHTLY_REPROCESS" in definition
    for still_allowed in ("INITIAL", "EOD_RETRY", "V2_FAST_RETRY"):
        assert still_allowed in definition


@pytest.mark.asyncio
async def test_attempt_type_check_allows_nightly_reprocess_from_attempt_three(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_processing_job_attempt_type'"
            )
        )
    ).scalar_one()
    assert "NIGHTLY_REPROCESS" in definition
    assert ">= 3" in definition


@pytest.mark.asyncio
async def test_processing_runs_run_type_check_allows_nightly_reprocess(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'processing_runs_run_type_check'"
            )
        )
    ).scalar_one()
    assert "NIGHTLY_REPROCESS" in definition
    for still_allowed in ("INITIAL", "EOD_RETRY", "V2_FAST_RETRY"):
        assert still_allowed in definition

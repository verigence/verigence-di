"""tests/test_processing_runs_run_type_constraint.py

Regression for migration 0039. Migration 0035 added the V2_FAST_RETRY
job_type but only updated the two CHECK constraints on
docintel.processing_jobs -- it missed the parallel constraint on
docintel.processing_runs (run_type, copied verbatim from job_type by
workers/job_runner.py when a run starts). Confirmed live: a V2_FAST_RETRY
job's run always failed at that INSERT with

    psycopg.errors.CheckViolation: new row for relation "processing_runs"
    violates check constraint "processing_runs_run_type_check"

-- meaning the fast retry could never actually run the extraction it
exists to run, for any tenant, since 0035 shipped.

Requires the real (Docker) Postgres test database -- this is what proves
the migration actually ran and the constraint actually changed, not just
that application code built the right SQL string.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_processing_runs_run_type_check_allows_v2_fast_retry(db_session) -> None:  # type: ignore[no-untyped-def]
    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'processing_runs_run_type_check'"
            )
        )
    ).scalar_one()
    assert "V2_FAST_RETRY" in definition
    # The two values this constraint has always allowed must still be
    # allowed -- this is strictly additive, never a narrowing.
    assert "INITIAL" in definition
    assert "EOD_RETRY" in definition

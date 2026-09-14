"""Allow a V2_FAST_RETRY processing_runs.run_type.

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-14

Migration 0035 added the V2_FAST_RETRY job_type but only updated the two
CHECK constraints on docintel.processing_jobs -- it missed the parallel
CHECK constraint on docintel.processing_runs (run_type, copied verbatim
from job_type by workers/job_runner.py when a run starts). The
processing_jobs row for a V2_FAST_RETRY job has therefore always inserted
fine, but starting its run has always failed:

    psycopg.errors.CheckViolation: new row for relation "processing_runs"
    violates check constraint "processing_runs_run_type_check"

-- confirmed live, 2026-09-14: a gst_declaration Capture V2 document's
fast-retry attempt failed at exactly this INSERT (job_runner_unexpected_
escape / job_failed_backout, error_code=DATABASE_UNAVAILABLE, retryable),
which means the fast retry can never actually run the extraction it
exists to run -- every V2_FAST_RETRY job for every tenant has been
failing at this same step since 0035 shipped, silently retried forever
by the RETRYABLE classification, leaving the underlying document stuck
exactly as long as the old once-daily EOD Retry Scheduler this feature
was built to avoid.
"""
from __future__ import annotations

from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY'))"
    )

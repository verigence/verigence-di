"""Allow a V2_FAST_RETRY processing job type.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-10

Document Capture V2's bounded worker pool exists specifically to give
extraction a fast, PC-facing turnaround (see workers/processor.py's module
docstring). Its first retryable extraction failure previously fell back to
the legacy EOD Retry Scheduler -- correct for the V1 flow, but it can leave
a V2 document showing nothing more than "still processing" for up to ~24h,
with no PC-visible sign it already failed once (processing_status =
'RETRY_PENDING' renders identically to "not yet extracted" on the capture
screen -- confirmed live: a Delivery journey's Payment Receipt/KYC documents
sat this way for hours with no forward progress and no visible failure).

repositories/processing_jobs.py's new schedule_v2_fast_retry() inserts a
second attempt (attempt_no=2, same convention as EOD_RETRY) a couple of
minutes later instead of waiting for the tenant's once-daily EOD window.
Both CHECK constraints from 0001_initial_schema.py that enumerate job_type
need the new value; ck_processing_job_attempt_type already pairs
attempt_no=2 with EOD_RETRY, so V2_FAST_RETRY is added to that same side.
"""
from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY'))"
    )
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type IN ('EOD_RETRY', 'V2_FAST_RETRY') AND attempt_no = 2)"
        ")"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type = 'EOD_RETRY' AND attempt_no = 2)"
        ")"
    )
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY'))"
    )

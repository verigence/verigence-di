"""Fix: processing_jobs_attempt_no_check still blocks NIGHTLY_REPROCESS.

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-22

0040 (Nightly Reprocessing) updated ck_processing_job_attempt_type to allow
NIGHTLY_REPROCESS with attempt_no >= 3, but missed a second, separate
constraint on the same column: 0001_initial_schema.py's inline column
definition `attempt_no integer NOT NULL CHECK (attempt_no IN (1,2))`,
auto-named processing_jobs_attempt_no_check by Postgres. Both constraints
are enforced simultaneously -- satisfying the new one was never enough
while the old one still capped every insert at 1 or 2.

Confirmed live: every NIGHTLY_REPROCESS insert since 0040 shipped
(2026-09-14) has hit this exact CheckViolation, caught by
insert_nightly_reprocessing_jobs' own try/except (a deliberate "one bad
row shouldn't abort the whole pass" handler, never meant to catch a
constraint every row hits), logged, and silently skipped -- the nightly
job has run every night, every tenant, and reported `documents_queued: 0`
indistinguishable from "nothing needed reprocessing." The whole feature
has never actually queued a single job in production.

ck_processing_job_attempt_type already fully encodes the correct
per-job_type range (1 for INITIAL, 2 for EOD_RETRY/V2_FAST_RETRY, >=3 for
NIGHTLY_REPROCESS) -- processing_jobs_attempt_no_check is now strictly
redundant, not just wrong, so this drops it rather than widening it to a
second hardcoded range that could drift out of sync with 0040's constraint
again.
"""
from __future__ import annotations

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_attempt_no_check"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_attempt_no_check "
        "CHECK (attempt_no IN (1, 2))"
    )

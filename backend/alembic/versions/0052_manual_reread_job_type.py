"""0052 — MANUAL_REREAD processing job type.

A page a person asks to be read again (Audit Core's "Read again" action on
the Upload / Edit Documents card, decision 2026-10-01) is queued as its own
job type so the attempt history says who asked. attempt_no is one more than
the document's last attempt and never below 2, so the first attempt stays
INITIAL. Same pattern as 0035/0040.
"""
from __future__ import annotations

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS', 'MANUAL_REREAD'))"
    )
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type IN ('EOD_RETRY', 'V2_FAST_RETRY') AND attempt_no = 2)"
        "  OR (job_type = 'NIGHTLY_REPROCESS' AND attempt_no >= 3)"
        "  OR (job_type = 'MANUAL_REREAD' AND attempt_no >= 2)"
        ")"
    )
    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS', 'MANUAL_REREAD'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS'))"
    )
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type IN ('EOD_RETRY', 'V2_FAST_RETRY') AND attempt_no = 2)"
        "  OR (job_type = 'NIGHTLY_REPROCESS' AND attempt_no >= 3)"
        ")"
    )
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS'))"
    )

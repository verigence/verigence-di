"""0054 — a second Capture V2 daytime retry (attempt 3).

Product owner's rule (2026-10-20, see verigence/di/retry_policy.py): a page
whose AI reading fails is tried again 10 minutes and then 20 minutes later,
so a V2_FAST_RETRY job can now be attempt 2 or attempt 3. The constraint
pairing job types with attempt numbers is widened for that one case; every
other pair is unchanged. Additive: no existing row is touched.
"""
from __future__ import annotations

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type = 'EOD_RETRY' AND attempt_no = 2)"
        "  OR (job_type = 'V2_FAST_RETRY' AND attempt_no IN (2, 3))"
        "  OR (job_type = 'NIGHTLY_REPROCESS' AND attempt_no >= 3)"
        "  OR (job_type = 'MANUAL_REREAD' AND attempt_no >= 2)"
        ")"
    )


def downgrade() -> None:
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

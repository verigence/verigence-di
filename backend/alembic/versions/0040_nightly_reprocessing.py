"""Nightly Reprocessing: retry FAILED documents a bounded number of times.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-14

A document that fails extraction twice (see 0035/0039) today never gets
another automatic attempt -- the backout queue is explicitly a dead letter
store ("No reprocessing is triggered from the backout queue"). Confirmed
live: a Capture V2 document's extraction failed on a transient Gemini API
timeout -- exactly the kind of failure a later retry would likely recover
from, but the existing design gives it none.

Nightly Reprocessing adds a bounded third-and-beyond chance: once a night,
at a fixed time, every currently-FAILED document that hasn't already used
up its reprocessing attempts gets one more processing_jobs row
(job_type='NIGHTLY_REPROCESS'). Nothing about the worker's own extraction
logic changes -- these are ordinary jobs, claimed and processed exactly
like INITIAL/EOD_RETRY/V2_FAST_RETRY jobs already are (see
_claim_next_job in repositories/processing_jobs.py, which already routes
by document_capture_v2_uploads presence, not by job_type). A
NIGHTLY_REPROCESS job that fails again goes through the exact same
_handle_failure path as any attempt_no != 1 failure already does: marked
FAILED, backout row refreshed, no code changes needed there.

Two constraint changes:

1. UNIQUE (tenant_id, document_id, job_type) on processing_jobs assumed
   exactly one row per (document, job_type) ever -- true for
   INITIAL/EOD_RETRY/V2_FAST_RETRY, each of which only ever fires once per
   document at a fixed attempt_no. NIGHTLY_REPROCESS needs multiple rows
   for the same document across different nights (attempt_no 3, 4, 5, ...),
   so the uniqueness widens to include attempt_no. This is additive only:
   every existing job_type still gets exactly one row per document, since
   each already always inserts the same fixed attempt_no.

2. job_type/run_type CHECK constraints (processing_jobs, processing_runs)
   and the job_type/attempt_no pairing CHECK (ck_processing_job_attempt_type)
   all gain the new value, following the exact pattern 0035 and 0039 used.
"""
from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_UNIQUE_CONSTRAINT = "processing_jobs_tenant_id_document_id_job_type_key"
_NEW_UNIQUE_CONSTRAINT = "processing_jobs_tenant_document_jobtype_attempt_key"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE docintel.processing_jobs DROP CONSTRAINT {_UNIQUE_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE docintel.processing_jobs ADD CONSTRAINT {_NEW_UNIQUE_CONSTRAINT} "
        "UNIQUE (tenant_id, document_id, job_type, attempt_no)"
    )

    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS'))"
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

    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY', 'NIGHTLY_REPROCESS'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_runs DROP CONSTRAINT processing_runs_run_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_runs ADD CONSTRAINT processing_runs_run_type_check "
        "CHECK (run_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY'))"
    )

    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT ck_processing_job_attempt_type")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT ck_processing_job_attempt_type "
        "CHECK ("
        "  (job_type = 'INITIAL' AND attempt_no = 1)"
        "  OR (job_type IN ('EOD_RETRY', 'V2_FAST_RETRY') AND attempt_no = 2)"
        ")"
    )

    op.execute("ALTER TABLE docintel.processing_jobs DROP CONSTRAINT processing_jobs_job_type_check")
    op.execute(
        "ALTER TABLE docintel.processing_jobs ADD CONSTRAINT processing_jobs_job_type_check "
        "CHECK (job_type IN ('INITIAL', 'EOD_RETRY', 'V2_FAST_RETRY'))"
    )

    op.execute(
        f"ALTER TABLE docintel.processing_jobs DROP CONSTRAINT {_NEW_UNIQUE_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE docintel.processing_jobs ADD CONSTRAINT {_UNIQUE_CONSTRAINT} "
        "UNIQUE (tenant_id, document_id, job_type)"
    )

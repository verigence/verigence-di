"""Once-per-night scheduler run markers; bounded stale-lease reclaims.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-29

1. docintel.scheduler_runs: the Nightly Reprocessing trigger window (±90s)
   spans several 60-second ticks, on every replica that runs the scheduler.
   One (run_name, run_date) row, claimed with ON CONFLICT DO NOTHING, lets a
   single tick queue the night's jobs and report the run to Audit Core once.
   A global (not tenant-scoped) table, like the job queues the scheduler reads.

2. processing_jobs.lease_reclaim_count: the stale-job reaper put an expired
   RUNNING job back to PENDING without limit, so a document that kills the
   worker every time was retried forever. attempt_no cannot carry this count
   (ck_processing_job_attempt_type pins it per job_type), hence a column.
"""
from __future__ import annotations

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS docintel.scheduler_runs (
            run_name            varchar(60) NOT NULL,
            run_date            date NOT NULL,
            claimed_by          varchar(160) NOT NULL,
            started_at_utc      timestamptz NOT NULL,
            completed_at_utc    timestamptz,
            items_queued        integer,
            error_code          varchar(120),
            PRIMARY KEY (run_name, run_date)
        )
        """
    )
    op.execute(
        "ALTER TABLE docintel.processing_jobs "
        "ADD COLUMN IF NOT EXISTS lease_reclaim_count integer NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE docintel.processing_jobs DROP COLUMN IF EXISTS lease_reclaim_count")
    op.execute("DROP TABLE IF EXISTS docintel.scheduler_runs")

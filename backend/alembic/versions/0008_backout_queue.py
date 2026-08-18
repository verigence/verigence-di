"""0008 — backout queue for failed processing jobs

Decision D24 (DI_DECISIONS.md): introduce docintel.backout_jobs as a
dead-letter store for any document that fails processing (retryable or
non-retryable). Rows expire after DI_BACKOUT_TTL_HOURS (default 12 h)
and are swept by the EODRetryScheduler on every 60-second tick.

No changes to existing tables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE docintel.backout_jobs (
            tenant_id           varchar(128)  NOT NULL,
            backout_job_id      uuid          NOT NULL,
            document_id         uuid          NOT NULL,
            processing_job_id   uuid          NOT NULL,
            processing_run_id   uuid,
            error_class         varchar(20)   NOT NULL
                                  CHECK (error_class IN ('RETRYABLE','NON_RETRYABLE')),
            error_code          varchar(120),
            error_detail        text,
            expires_at_utc      timestamptz   NOT NULL,
            created_at_utc      timestamptz   NOT NULL,
            PRIMARY KEY (tenant_id, backout_job_id),
            UNIQUE (tenant_id, document_id),
            FOREIGN KEY (tenant_id, document_id)
              REFERENCES docintel.documents(tenant_id, document_id),
            FOREIGN KEY (tenant_id, processing_job_id)
              REFERENCES docintel.processing_jobs(tenant_id, processing_job_id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_backout_jobs_ttl
        ON docintel.backout_jobs(expires_at_utc)
    """)
    op.execute("""
        CREATE INDEX ix_backout_jobs_document
        ON docintel.backout_jobs(tenant_id, document_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS docintel.backout_jobs")

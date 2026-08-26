"""UC03 PC Booking direct-DI document linkage state.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-26
"""
from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE docintel.documents
            ADD COLUMN audit_requirement_ref varchar(160),
            ADD COLUMN audit_link_status varchar(20) NOT NULL DEFAULT 'NOT_REQUIRED',
            ADD COLUMN audit_link_attempt_count integer NOT NULL DEFAULT 0,
            ADD COLUMN audit_link_last_attempt_at_utc timestamptz,
            ADD COLUMN audit_link_acknowledged_at_utc timestamptz,
            ADD COLUMN audit_link_last_error text
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.documents
        ADD CONSTRAINT ck_documents_audit_link_status
        CHECK (audit_link_status IN ('NOT_REQUIRED','PENDING','ACKNOWLEDGED'))
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.documents
        ADD CONSTRAINT ck_documents_audit_link_attempt_count
        CHECK (audit_link_attempt_count >= 0)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_documents_pending_audit_link
        ON docintel.documents (tenant_id, registered_at_utc, document_id)
        WHERE audit_link_status = 'PENDING'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS docintel.ix_documents_pending_audit_link")
    op.execute(
        "ALTER TABLE docintel.documents "
        "DROP CONSTRAINT IF EXISTS ck_documents_audit_link_attempt_count"
    )
    op.execute(
        "ALTER TABLE docintel.documents "
        "DROP CONSTRAINT IF EXISTS ck_documents_audit_link_status"
    )
    op.execute(
        """
        ALTER TABLE docintel.documents
            DROP COLUMN IF EXISTS audit_link_last_error,
            DROP COLUMN IF EXISTS audit_link_acknowledged_at_utc,
            DROP COLUMN IF EXISTS audit_link_last_attempt_at_utc,
            DROP COLUMN IF EXISTS audit_link_attempt_count,
            DROP COLUMN IF EXISTS audit_link_status,
            DROP COLUMN IF EXISTS audit_requirement_ref
        """
    )

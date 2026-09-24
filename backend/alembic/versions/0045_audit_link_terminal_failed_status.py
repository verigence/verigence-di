"""Add a terminal FAILED status for a permanently-broken audit-link.

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-24

Found live via Railway logs: the audit-link delivery worker
(_process_pending_audit_link in workers/processor.py) has no terminal
failure state at all -- a non-retryable failure (e.g. VAC-NF-006, "The
supplied requirementRef is not an active Booking or Delivery document
requirement", a 404 that can never succeed by retrying) is recorded via
mark_audit_link_attempt with acknowledged=False, which leaves
audit_link_status at 'PENDING' regardless of retryable. claim_pending_audit_link
only filters on audit_link_status='PENDING', so the SAME permanently-broken
link keeps getting reclaimed forever, backed off to a 60-second ceiling
(audit_link_retry_delay_seconds) but never actually given up on. Observed
live at attempt counts in the 900s for a handful of documents -- roughly
15 hours of continuous, guaranteed-to-fail retries, one HTTP round trip
to Audit Core every cycle.

This migration only widens the CHECK constraint to allow 'FAILED' as a
fourth value. The worker-side change (this migration's paired code
change) is what actually stops writing 'PENDING' for a non-retryable
failure and writes 'FAILED' instead, which claim_pending_audit_link's own
WHERE clause then naturally excludes from ever being reclaimed again.
"""
from __future__ import annotations

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE docintel.documents DROP CONSTRAINT ck_documents_audit_link_status")
    op.execute(
        "ALTER TABLE docintel.documents ADD CONSTRAINT ck_documents_audit_link_status "
        "CHECK (audit_link_status IN ('NOT_REQUIRED','PENDING','ACKNOWLEDGED','FAILED'))"
    )


def downgrade() -> None:
    # Any row already written as 'FAILED' by the worker-side change would
    # violate the narrower constraint -- reclassify it back to 'PENDING'
    # (its pre-0045 behavior: eligible for the worker to reclaim again)
    # before restoring the original three-value constraint.
    op.execute("UPDATE docintel.documents SET audit_link_status = 'PENDING' WHERE audit_link_status = 'FAILED'")
    op.execute("ALTER TABLE docintel.documents DROP CONSTRAINT ck_documents_audit_link_status")
    op.execute(
        "ALTER TABLE docintel.documents ADD CONSTRAINT ck_documents_audit_link_status "
        "CHECK (audit_link_status IN ('NOT_REQUIRED','PENDING','ACKNOWLEDGED'))"
    )

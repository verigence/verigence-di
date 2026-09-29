"""Capture V2: let the caller trust a single, already-known document type.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-28

Audit Core Phase 2 splits an upload into pages, has DI classify each page,
then merges the pages of one business document (booking form pair, Aadhaar
front/back, statements) and uploads the merged document with exactly that
one type as its candidate. Classifying it again is a second paid Gemini call
for an answer already known. ``classification_mode = TRUST_SINGLE_CANDIDATE``
(only valid with exactly one candidate) skips that call; upload validation
and extraction are unchanged. The default ``CLASSIFY`` keeps today's
behaviour for every other caller.
"""
from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        ADD COLUMN IF NOT EXISTS classification_mode varchar(32) NOT NULL DEFAULT 'CLASSIFY'
        """
    )
    # Drop first so a database that already carries the constraint (schema ahead
    # of its version stamp) can still finish the upgrade.
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_classification_mode"
    )
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        ADD CONSTRAINT ck_capture_v2_uploads_classification_mode
        CHECK (classification_mode IN ('CLASSIFY', 'TRUST_SINGLE_CANDIDATE'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_classification_mode"
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads DROP COLUMN IF EXISTS classification_mode"
    )

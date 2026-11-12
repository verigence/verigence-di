"""0066 -- types Audit Core asks DI to classify but not read, per upload (2026-11-12).

Product owner, 12 Nov 2026: "classification still happens but extraction won't for
documents already uploaded", and "UPI receipts can be ignored to be extracted and this
should be standard rule across". DI cannot know what a journey already holds; Audit
Core does. ``document_capture_v2_uploads.read_skip_document_type_keys`` is the list of
types Audit Core sends with the upload: a page classified as one of them is classified
and not queued for reading (``extractionQueued=false``, as for a type that is not read),
and Audit Core keeps it as supporting evidence.

Additive; idempotent; every existing row reads as "skip nothing".
"""
from __future__ import annotations

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "ADD COLUMN IF NOT EXISTS read_skip_document_type_keys jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP COLUMN IF EXISTS read_skip_document_type_keys"
    )

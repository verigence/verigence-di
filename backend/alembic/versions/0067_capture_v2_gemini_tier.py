"""0067 -- the Gemini service tier an upload is read at (2026-11-12).

Product owner, 12 Nov 2026: the Drive intake is "to be used as batch ... take the advantage
of batch process of Gemini API which will lower the cost". Gemini's Flex tier is priced like
the Batch API (half the standard price) but answers the same call, in minutes instead of
seconds, and is offered for gemini-3-flash-preview (the Batch API page does not list it).
``document_capture_v2_uploads.gemini_tier``:

- STANDARD (default, every existing row): as before.
- FLEX: the first classification and the first extraction of the upload go to Gemini's Flex
  tier; a retry goes to the standard tier, so a busy Flex tier never holds a page past the
  retry rule.

Additive; idempotent.
"""
from __future__ import annotations

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "ADD COLUMN IF NOT EXISTS gemini_tier varchar(16) NOT NULL DEFAULT 'STANDARD'"
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_gemini_tier"
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "ADD CONSTRAINT ck_capture_v2_uploads_gemini_tier CHECK (gemini_tier IN ('STANDARD', 'FLEX'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_gemini_tier"
    )
    op.execute("ALTER TABLE docintel.document_capture_v2_uploads DROP COLUMN IF EXISTS gemini_tier")

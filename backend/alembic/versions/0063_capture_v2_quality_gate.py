"""0063 -- an upload the person confirmed after a scan-quality refusal (2026-11-06).

Product owner: "I have seen pics being correct only ... we have to take the same
page and upload." The scan-quality rules (size, blur, contrast) give the same
verdict for the same bytes every time, so a readable page they refuse can never
get in. ``document_capture_v2_uploads.quality_gate``:

- ENFORCE (default, every existing row): a failed scan-quality rule refuses the page.
- UPLOADER_CONFIRMED: the caller (Audit Core) says the person sent this refused
  page again as it is. The rules still run and their scores are recorded; a
  failed size, blur or contrast rule no longer refuses it. Empty, corrupt or
  over-long files are still refused.

Additive; idempotent.
"""
from __future__ import annotations

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "ADD COLUMN IF NOT EXISTS quality_gate varchar(32) NOT NULL DEFAULT 'ENFORCE'"
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_quality_gate"
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "ADD CONSTRAINT ck_capture_v2_uploads_quality_gate "
        "CHECK (quality_gate IN ('ENFORCE', 'UPLOADER_CONFIRMED'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads "
        "DROP CONSTRAINT IF EXISTS ck_capture_v2_uploads_quality_gate"
    )
    op.execute("ALTER TABLE docintel.document_capture_v2_uploads DROP COLUMN IF EXISTS quality_gate")

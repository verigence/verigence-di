"""0070 -- what a classification costs (2026-11-16).

Product owner, 16 Nov 2026: "if we can capture the cost it will help ... I would like to
know how much cost we are entailing". A read already keeps its tokens on
``processor_invocations.usage_metrics``; a classification kept nothing (its tokens went to
a log line only), so about half of the provider calls had no recorded cost.

``document_capture_v2_classification_jobs.usage_metrics`` (jsonb, NULL until a provider
call is made for the job) holds the job's running totals across its attempts: provider
calls, prompt / answer / thinking tokens, the service tier and prices in force, and
``cost_usd``. A job whose single candidate was trusted makes no call and stays NULL.

Additive; idempotent. Rows written before this migration stay NULL: their tokens were
never stored and are not estimated.
"""
from __future__ import annotations

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_classification_jobs "
        "ADD COLUMN IF NOT EXISTS usage_metrics jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_classification_jobs "
        "DROP COLUMN IF EXISTS usage_metrics"
    )

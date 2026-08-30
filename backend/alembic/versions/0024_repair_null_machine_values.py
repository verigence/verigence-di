"""Repair historical MACHINE field values that lost a real extraction.

Before the lossless-normalization fix, a normalization failure could persist a
consumer-visible null even when the immutable machine fact was ``FOUND`` and
still retained a non-empty ``raw_value_text``. Depending on the write path, that
null may be SQL NULL or JSONB ``null``. Audit Core reads the current machine value,
so those rows appeared in UC03 Review as "not extracted" even though DI had
extracted the value.

This migration repairs only that inconsistent state. It does not manufacture
values for NOT_FOUND facts and it does not overwrite any real non-null value.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE docintel.document_field_values AS dfv
            SET current_value = (
                    SELECT COALESCE(
                        NULLIF(ef.normalized_value, 'null'::jsonb),
                        to_jsonb(ef.raw_value_text)
                    )
                    FROM docintel.extracted_facts AS ef
                    WHERE ef.tenant_id = dfv.tenant_id
                      AND ef.document_id = dfv.document_id
                      AND ef.canonical_field_id = dfv.canonical_field_id
                      AND ef.found_status = 'FOUND'
                      AND (
                          NULLIF(ef.normalized_value, 'null'::jsonb) IS NOT NULL
                          OR NULLIF(BTRIM(ef.raw_value_text), '') IS NOT NULL
                      )
                    ORDER BY ef.created_at_utc DESC, ef.extracted_fact_id DESC
                    LIMIT 1
                )
            WHERE dfv.is_current = true
              AND dfv.value_source = 'MACHINE'
              AND (
                    dfv.current_value IS NULL
                    OR dfv.current_value = 'null'::jsonb
                  )
              AND EXISTS (
                    SELECT 1
                    FROM docintel.extracted_facts AS ef
                    WHERE ef.tenant_id = dfv.tenant_id
                      AND ef.document_id = dfv.document_id
                      AND ef.canonical_field_id = dfv.canonical_field_id
                      AND ef.found_status = 'FOUND'
                      AND (
                          NULLIF(ef.normalized_value, 'null'::jsonb) IS NOT NULL
                          OR NULLIF(BTRIM(ef.raw_value_text), '') IS NOT NULL
                      )
                )
            """
        )
    )


def downgrade() -> None:
    # This is a data-repair migration. Reverting repaired values to null would
    # intentionally reintroduce data loss, so downgrade is a no-op.
    pass

"""0007_gemini_schema_registry

Implements DI_DECISIONS.md D14, D16, D18, D23:

1.  pg_trgm extension (D14 — required for fuzzy search on document_search_index)
2.  document_search_index table + indexes (D14)
3.  New global seed document types for dealer audit domain (D16 + D23):
      booking_form, dealer_receipt, bank_statement_extract,
      upi_transaction, delivery_order_cover, upi_screenshot
4.  UPDATE tenant_document_types SET requires_processing = true (D18)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-19
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# New global seed document types (D16 + D23).
# key                      display_name               category
# insurance_cover already exists from migration 0005 — not repeated here.
_NEW_DOCUMENT_TYPES = [
    ("booking_form",           "Booking Form",           "HANDWRITTEN"),
    ("dealer_receipt",         "Dealer Receipt",         "PRINTABLE"),
    ("bank_statement_extract", "Bank Statement Extract", "PRINTABLE"),
    ("upi_transaction",        "UPI Transaction",        "ADDITIONAL"),
    ("delivery_order_cover",   "Delivery Order Cover",   "PRINTABLE"),
    ("upi_screenshot",         "UPI Screenshot",         "ADDITIONAL"),
]


def upgrade() -> None:
    # ── 1. pg_trgm extension (D14) ────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── 2. document_search_index table (D14) ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS docintel.document_search_index (
            tenant_id           varchar(128)    NOT NULL,
            document_id         uuid            NOT NULL,
            subject_id          uuid,
            document_type_key   varchar(120),
            indexed_fields      jsonb           NOT NULL DEFAULT '{}',
            schema_version      varchar(20),
            created_at_utc      timestamptz     NOT NULL DEFAULT NOW() AT TIME ZONE 'UTC',
            updated_at_utc      timestamptz     NOT NULL DEFAULT NOW() AT TIME ZONE 'UTC',
            PRIMARY KEY (tenant_id, document_id),
            FOREIGN KEY (tenant_id)
                REFERENCES docintel.tenant_settings(tenant_id),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES docintel.documents(tenant_id, document_id)
        )
    """)

    # GIN index for JSONB containment queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_document_search_index_fields
        ON docintel.document_search_index
        USING GIN (indexed_fields)
    """)

    # btree index for subject-scoped queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_document_search_index_subject
        ON docintel.document_search_index (tenant_id, subject_id)
    """)

    # ── 3. Seed new global document types (D16 + D23) ────────────────────────
    for key, display_name, category in _NEW_DOCUMENT_TYPES:
        op.execute(f"""
            INSERT INTO docintel.document_types
                (document_type_id, owner_tenant_id, document_type_key,
                 display_name, description, category, status,
                 created_at_utc, updated_at_utc)
            SELECT
                gen_random_uuid(),
                NULL,
                '{key}',
                '{display_name}',
                NULL,
                '{category}',
                'ACTIVE',
                NOW() AT TIME ZONE 'UTC',
                NOW() AT TIME ZONE 'UTC'
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE document_type_key = '{key}'
                  AND owner_tenant_id IS NULL
            )
        """)

    # ── 4. Flip requires_processing = true for all tenant_document_types (D18) ─
    # D18 supersedes D4: every document type is processed regardless of form type.
    # ADDITIONAL types that were previously skipped now also get OCR.
    op.execute("""
        UPDATE docintel.tenant_document_types
        SET requires_processing = true,
            updated_at_utc = NOW() AT TIME ZONE 'UTC'
        WHERE requires_processing = false
    """)


def downgrade() -> None:
    # ── Reverse 4: restore requires_processing = false for ADDITIONAL types ──
    op.execute("""
        UPDATE docintel.tenant_document_types tdt
        SET requires_processing = false,
            updated_at_utc = NOW() AT TIME ZONE 'UTC'
        FROM docintel.document_types dt
        WHERE dt.document_type_id = tdt.document_type_id
          AND COALESCE(dt.category, 'ADDITIONAL') = 'ADDITIONAL'
    """)

    # ── Reverse 3: remove seeded document types ───────────────────────────────
    keys = ", ".join(f"'{k}'" for k, _, _ in _NEW_DOCUMENT_TYPES)
    op.execute(f"""
        DELETE FROM docintel.document_types
        WHERE owner_tenant_id IS NULL
          AND document_type_key IN ({keys})
    """)

    # ── Reverse 2: drop document_search_index ────────────────────────────────
    op.execute("DROP TABLE IF EXISTS docintel.document_search_index")

    # ── Reverse 1: extension is shared — do not drop pg_trgm ─────────────────
    # pg_trgm may be used by other objects; dropping it is unsafe in downgrade.

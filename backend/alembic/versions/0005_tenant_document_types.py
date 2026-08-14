"""0005_tenant_document_types

Implements DI_DECISIONS.md D1–D7:

1. Seed global document_types rows (15 standard types).
2. Add tenant_document_types table — per-tenant form type + processing flag.
3. Add physical_form_type + requires_processing columns to documents.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


# Global seed document types (D1).
# category column holds the default physical_form_type for human reference.
_SEED_DOCUMENT_TYPES = [
    # key                   display_name                 category
    ("pan_card",            "PAN Card",                  "GOVT_ID"),
    ("aadhaar",             "Aadhaar Card",              "GOVT_ID"),
    ("passport",            "Passport",                  "GOVT_ID"),
    ("driving_licence",     "Driving Licence",           "GOVT_ID"),
    ("voter_id",            "Voter ID",                  "GOVT_ID"),
    ("corporate_id",        "Corporate ID",              "PRINTABLE"),
    ("bank_statement",      "Bank Statement",            "PRINTABLE"),
    ("loan_statement",      "Loan Statement",            "PRINTABLE"),
    ("customer_ledger",     "Customer Ledger",           "PRINTABLE"),
    ("insurance_cover",     "Insurance Cover Note",      "PRINTABLE"),
    ("utility_bill",        "Utility Bill",              "PRINTABLE"),
    ("booking_docket",      "Booking Docket",            "PRINTABLE"),
    ("salary_slip",         "Salary Slip",               "PRINTABLE"),
    ("signed_declaration",  "Signed Declaration",        "HANDWRITTEN"),
    ("supporting_document", "Supporting Document",       "ADDITIONAL"),
]

# Default physical_form_type per category — used when seeding tenant_document_types.
_REQUIRES_PROCESSING = {
    "GOVT_ID":     True,
    "PRINTABLE":   True,
    "HANDWRITTEN": True,
    "ADDITIONAL":  False,
}


def upgrade() -> None:
    # ── 1. Seed global document_types ────────────────────────────────────────
    # owner_tenant_id IS NULL = global (visible to all tenants).
    # ON CONFLICT DO NOTHING — safe to re-run.
    for key, display_name, category in _SEED_DOCUMENT_TYPES:
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

    # ── 2. Create tenant_document_types table (D2, D3) ───────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS docintel.tenant_document_types (
            tenant_id           varchar(128) NOT NULL,
            document_type_id    uuid         NOT NULL,
            physical_form_type  varchar(20)  NOT NULL
                CHECK (physical_form_type IN
                       ('GOVT_ID','PRINTABLE','HANDWRITTEN','ADDITIONAL')),
            requires_processing boolean      NOT NULL DEFAULT true,
            is_active           boolean      NOT NULL DEFAULT true,
            display_order       integer      NOT NULL DEFAULT 100,
            created_at_utc      timestamptz  NOT NULL,
            updated_at_utc      timestamptz  NOT NULL,
            PRIMARY KEY (tenant_id, document_type_id),
            FOREIGN KEY (tenant_id)
                REFERENCES docintel.tenant_settings(tenant_id),
            FOREIGN KEY (document_type_id)
                REFERENCES docintel.document_types(document_type_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tenant_doc_types_tenant
        ON docintel.tenant_document_types(tenant_id, is_active)
    """)

    # ── 3. Add physical_form_type + requires_processing to documents (D4) ───
    op.execute("""
        ALTER TABLE docintel.documents
            ADD COLUMN IF NOT EXISTS physical_form_type varchar(20)
                CHECK (physical_form_type IS NULL OR physical_form_type IN
                       ('GOVT_ID','PRINTABLE','HANDWRITTEN','ADDITIONAL'))
    """)

    op.execute("""
        ALTER TABLE docintel.documents
            ADD COLUMN IF NOT EXISTS requires_processing boolean
                NOT NULL DEFAULT true
    """)

    # Backfill existing rows — already uploaded docs default to ADDITIONAL/false
    # since we cannot know their form type retroactively.
    op.execute("""
        UPDATE docintel.documents
        SET physical_form_type = 'ADDITIONAL',
            requires_processing = false
        WHERE physical_form_type IS NULL
    """)


def downgrade() -> None:
    # ── Reverse 3: drop columns from documents ────────────────────────────────
    op.execute("""
        ALTER TABLE docintel.documents
            DROP COLUMN IF EXISTS requires_processing
    """)
    op.execute("""
        ALTER TABLE docintel.documents
            DROP COLUMN IF EXISTS physical_form_type
    """)

    # ── Reverse 2: drop tenant_document_types ────────────────────────────────
    op.execute("DROP TABLE IF EXISTS docintel.tenant_document_types")

    # ── Reverse 1: remove seeded global document_types ───────────────────────
    keys = ", ".join(f"'{k}'" for k, _, _ in _SEED_DOCUMENT_TYPES)
    op.execute(f"""
        DELETE FROM docintel.document_types
        WHERE owner_tenant_id IS NULL
          AND document_type_key IN ({keys})
    """)

"""0009_invoice_document_types

Seed the global document types for the vehicle invoice / deal-sheet domain.

One superset ``invoice`` type: the document classifier cannot reliably tell a
vehicle Tax Invoice from a Retail / Accessories / Extended-Warranty invoice
(the layouts overlap), so every dealer invoice is classified as ``invoice``
and extracted against a single superset schema
(``document_ai/schemas/invoice.py``); the ``invoice_kind`` field is set during
extraction.

  invoice                   — Invoice (superset: tax / retail / accessories / EW)
  dealer_accounts_statement — Dealer Accounts Statement (the dealer deal sheet)
  rto_tax_receipt           — RTO Tax Receipt (registration / road-tax / permit fees)

Follows the pattern of migration 0007: seed ``docintel.document_types`` only.
Extraction profiles + canonical fields for these types are created through the
Extraction Profile admin API, not here.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# key                        display_name                  category
_NEW_DOCUMENT_TYPES = [
    ("invoice",                   "Invoice",                    "PRINTABLE"),
    ("dealer_accounts_statement", "Dealer Accounts Statement",  "PRINTABLE"),
    ("rto_tax_receipt",           "RTO Tax Receipt",            "PRINTABLE"),
]


def upgrade() -> None:
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
                now(),
                now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE document_type_key = '{key}'
                  AND owner_tenant_id IS NULL
            )
        """)


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k, _, _ in _NEW_DOCUMENT_TYPES)
    op.execute(f"""
        DELETE FROM docintel.document_types
        WHERE owner_tenant_id IS NULL
          AND document_type_key IN ({keys})
    """)

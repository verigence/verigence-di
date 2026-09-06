"""Register the debit_note and purchase_order global document types.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-06

Both are audit evidence sources the deterministic audit layer reconciles:
- debit_note: dealer charge note for insurance premium / RTO charges, checked
  against the insurance cover note and the RTO challan.
- purchase_order: corporate customer's PO, checked against the customer invoice
  and used to confirm a corporate deal is PO-backed.

Extraction schemas live in ``document_ai/schemas/{debit_note,purchase_order}.py``
and are registered in the schema registry; this migration adds the matching
global ``document_types`` rows (per D20). Additive only.
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_DOCUMENT_TYPES = [
    ("debit_note", "Debit Note", "PRINTABLE"),
    ("purchase_order", "Purchase Order", "PRINTABLE"),
]


def upgrade() -> None:
    for key, display_name, category in _DOCUMENT_TYPES:
        op.execute(
            f"""
            INSERT INTO docintel.document_types
                (document_type_id, owner_tenant_id, document_type_key,
                 display_name, description, category, status,
                 created_at_utc, updated_at_utc)
            SELECT
                gen_random_uuid(), NULL, '{key}', '{display_name}', NULL,
                '{category}', 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE document_type_key = '{key}' AND owner_tenant_id IS NULL
            )
            """
        )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k, _, _ in _DOCUMENT_TYPES)
    op.execute(
        f"""
        DELETE FROM docintel.document_types
        WHERE owner_tenant_id IS NULL AND document_type_key IN ({keys})
        """
    )

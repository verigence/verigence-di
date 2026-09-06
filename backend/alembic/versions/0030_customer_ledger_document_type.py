"""Register the customer_ledger global document type.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-06

The customer ledger (dealer's DMS/Tally account statement for one buyer) is a
first-class audit evidence source: it is the money-posting view the audit layer
reconciles against the invoice, the payment receipts and the finance sanction.
The extraction schema is added in
``document_ai/schemas/customer_ledger.py`` and registered in the schema
registry; this migration adds the matching global ``document_types`` row so the
registry key resolves (per D20).

Additive only. Tenant-specific extraction-profile publication, where a tenant
uses the profile-driven path, remains a separate step.
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_KEY = "customer_ledger"
_DISPLAY_NAME = "Customer Ledger"
_CATEGORY = "PRINTABLE"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO docintel.document_types
            (document_type_id, owner_tenant_id, document_type_key,
             display_name, description, category, status,
             created_at_utc, updated_at_utc)
        SELECT
            gen_random_uuid(), NULL, '{_KEY}', '{_DISPLAY_NAME}', NULL,
            '{_CATEGORY}', 'ACTIVE', now(), now()
        WHERE NOT EXISTS (
            SELECT 1 FROM docintel.document_types
            WHERE document_type_key = '{_KEY}' AND owner_tenant_id IS NULL
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM docintel.document_types
        WHERE owner_tenant_id IS NULL AND document_type_key = '{_KEY}'
        """
    )

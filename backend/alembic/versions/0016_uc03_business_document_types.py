"""Add the UC03 Booking/Delivery business document catalogue.

The business process defines the documents that a Process Consultant must verify.
Some already have extraction profiles; the remaining document types are valid
manual-review evidence until an Admin publishes an extraction profile for them.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-24
"""
from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# Existing DI types such as booking_docket, pan_card, aadhaar, customer_ledger and
# insurance_cover are intentionally not repeated here.
_DOCUMENT_TYPES = (
    # key, display name, physical form
    ("minimum_booking_payment_proof", "Minimum Booking Amount Payment Proof", "ADDITIONAL"),
    ("gst_certificate", "GST Certificate", "PRINTABLE"),
    ("vehicle_rc", "Vehicle Registration Certificate (RC)", "GOVT_ID"),
    ("transfer_letter", "Vehicle Transfer Letter", "HANDWRITTEN"),
    ("authorization_letter", "Authorization Letter", "HANDWRITTEN"),
    ("wholesale_invoice", "Wholesale Invoice", "PRINTABLE"),
    ("customer_invoice_dms", "Customer Invoice (DMS)", "PRINTABLE"),
    ("tax_invoice_tally", "Tax Invoice (Tally)", "PRINTABLE"),
    ("accessory_invoice_dms", "Accessory Invoice / Challan (DMS)", "PRINTABLE"),
    ("accessory_invoice_tally", "Accessory Invoice (Tally)", "PRINTABLE"),
    ("rto_challan", "RTO Challan", "PRINTABLE"),
    ("cost_sheet", "Cost Sheet", "PRINTABLE"),
    ("gate_pass", "Gate Pass", "PRINTABLE"),
    ("customer_kyc", "Customer KYC", "PRINTABLE"),
    ("ew_invoice", "Extended Warranty Invoice", "PRINTABLE"),
    ("rsa_invoice", "RSA Invoice", "PRINTABLE"),
    ("value_added_service_document", "Other Value Added Service Document", "PRINTABLE"),
    ("no_dues_certificate", "No Dues Certificate", "PRINTABLE"),
    ("payment_receipt", "Payment Receipt", "PRINTABLE"),
)


def upgrade() -> None:
    # These types are configuration/catalogue only. Until an Admin publishes a
    # matching extraction profile they remain valid evidence with manual review,
    # so requires_processing is false for the newly introduced types.
    for key, display_name, physical_form in _DOCUMENT_TYPES:
        safe_name = display_name.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO docintel.document_types (
                document_type_id, owner_tenant_id, document_type_key,
                display_name, description, category, status,
                created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, '{key}', '{safe_name}', NULL,
                   '{physical_form}', 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1
                FROM docintel.document_types
                WHERE owner_tenant_id IS NULL
                  AND document_type_key = '{key}'
            )
            """
        )

    # Existing Projects must see the same catalogue immediately. Future Projects
    # inherit all active global document types through normal DI provisioning.
    op.execute(
        """
        INSERT INTO docintel.tenant_document_types (
            tenant_id, document_type_id, physical_form_type,
            requires_processing, is_active, display_order,
            created_at_utc, updated_at_utc
        )
        SELECT ts.tenant_id,
               dt.document_type_id,
               COALESCE(dt.category, 'ADDITIONAL'),
               false,
               true,
               100,
               now(),
               now()
        FROM docintel.tenant_settings ts
        JOIN docintel.document_types dt
          ON dt.owner_tenant_id IS NULL
         AND dt.status = 'ACTIVE'
         AND dt.document_type_key IN (
            'minimum_booking_payment_proof','gst_certificate','vehicle_rc',
            'transfer_letter','authorization_letter','wholesale_invoice',
            'customer_invoice_dms','tax_invoice_tally','accessory_invoice_dms',
            'accessory_invoice_tally','rto_challan','cost_sheet','gate_pass',
            'customer_kyc','ew_invoice','rsa_invoice',
            'value_added_service_document','no_dues_certificate','payment_receipt'
         )
        ON CONFLICT (tenant_id, document_type_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Do not delete document types that are already referenced by evidence.
    # A forward-only configuration migration is safer for immutable audit history.
    pass

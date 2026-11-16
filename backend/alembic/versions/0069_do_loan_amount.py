"""The Delivery Order reads the loan (delivery_order_cover schema 1.2), and a
financier's loan email is a Delivery Order.

Revision ID: 0069
Revises: 0068
Create Date: 2026-11-16

Product owner 2026-11-16: the Audit Summary should show the loan amount when it
can be read from the Delivery Order, a payment receipt or the financier's
email, one figure chosen by deterministic code. The DO profile read no amount
at all; a financier's DO letter, disbursement advice or email was filed as
supporting_document and nothing of it was kept (453 of 872 financed bookings on
the live tenant have no disbursement on record).

delivery_order_cover schema 1.2 adds financier_name, loan_amount,
disbursement_date and disbursement_reference (all optional); this publishes
the matching profile (the published fields carried over unchanged plus the
new ones) and retires the old one. Its classifier definition now covers the
financier's DO, disbursement advice and email, and supporting_document's sends
a financier's loan email there. Audit Core files delivery_order_cover as
"Delivery Order (Financier)".

_FIELDS and _DEFINITIONS are snapshots (a migration must not import app code);
tests/test_do_loan_amount_profile.py and tests/test_document_type_definitions.py
pin them. NOTHING IS RE-CLASSIFIED OR RE-EXTRACTED here. Forward-only, like 0061.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

_ACTOR = "migration.0069.do-loan-amount"
_TYPE_KEY = "delivery_order_cover"

# (field_key, canonical data_type, instruction, expected, display_sequence)
# Snapshot of DELIVERY_ORDER_SCHEMA 1.2. A field the published profile already
# has keeps its published instruction.
_FIELDS: tuple[tuple[str, str, str, bool, int], ...] = (
    ('dealer_name', 'STRING',
     'Dealership name if explicitly visible', False, 10),
    ('delivery_order_number', 'IDENTIFIER',
     'Delivery order/DO number exactly as visible', False, 20),
    ('delivery_date', 'DATE',
     'Vehicle delivery/handover date if explicitly visible', False, 30),
    ('customer_name', 'STRING',
     'Customer receiving the vehicle', True, 40),
    ('booking_reference_number', 'IDENTIFIER',
     'Linked booking/order/reference number if visible', False, 50),
    ('vehicle_model', 'STRING',
     'Vehicle model exactly as visible', False, 60),
    ('vehicle_variant', 'STRING',
     'Vehicle variant/trim exactly as visible', False, 70),
    ('vehicle_color', 'STRING',
     'Vehicle colour exactly as visible', False, 80),
    ('chassis_number', 'IDENTIFIER',
     'Chassis/VIN exactly as visible; never reconstruct missing characters', False, 90),
    ('engine_number', 'IDENTIFIER',
     'Engine number exactly as visible; never reconstruct missing characters', False, 100),
    ('vehicle_registration_number', 'IDENTIFIER',
     'Vehicle registration number if explicitly visible', False, 110),
    ('delivered_by', 'STRING',
     'Sales/delivery executive name if explicitly visible', False, 120),
    ('embedded_document_types', 'JSON',
     'Other document types explicitly listed as included/attached; do not infer from an unseen bundle', False, 130),
    ('financier_name', 'STRING',
     'Financier / bank / NBFC named as funding the vehicle, exactly as printed', False, 140),
    ('loan_amount', 'CURRENCY',
     'Loan, finance or DO amount the financier pays for this vehicle, exactly as printed; never the vehicle price, down payment or margin money', False, 150),
    ('disbursement_date', 'DATE',
     'Date the loan was disbursed / paid to the dealer, only when printed', False, 160),
    ('disbursement_reference', 'IDENTIFIER',
     'UTR / transaction / cheque reference of the disbursement, only when printed', False, 170),
)

# Written onto the global rows.
_DEFINITIONS: dict[str, str] = {
    'delivery_order_cover': (
        "A delivery order (DO) for the vehicle: the dealer's DO or delivery cover sheet (DO number, delivery date, customer, model, chassis, who delivered it, documents attached), or a financier's DO, disbursement advice or email to the dealer to deliver against the loan (loan or disbursed amount, date, UTR). Not the sanction letter with tenure, rate and EMI (bank_approval_letter)."
    ),
    'supporting_document': (
        'Any page that is none of the other candidates, e.g. an email or approval note printout (a financier\'s loan email is delivery_order_cover), a Transaction Regularization Form, a covering letter or an insurer\'s premium receipt. A Form 21 (Sale Certificate, "See Rule 47") is form_21 and a New Vehicle Delivery Receipt (vehicle handed over, no amount) is delivery_receipt when those are candidates; otherwise they are supporting_document.'
    ),
}


def _publisher():
    """The cost sheet migration's republishing steps (0061), reused with this
    type, actor and snapshot."""
    path = Path(__file__).resolve().parent / "0061_cost_sheet_rows.py"
    spec = importlib.util.spec_from_file_location("mig_0061_publisher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._ACTOR = _ACTOR
    module._TYPE_KEY = _TYPE_KEY
    module._FIELDS = _FIELDS
    module._OLD_KEY_FOR = {}
    return module


def upgrade() -> None:
    _publisher().upgrade()
    conn = op.get_bind()
    for key, definition in _DEFINITIONS.items():
        conn.execute(
            sa.text(
                "UPDATE docintel.document_types SET description=:d, updated_at_utc=now() "
                "WHERE document_type_key=:k AND owner_tenant_id IS NULL"
            ),
            {"d": definition, "k": key},
        )


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0061).
    pass

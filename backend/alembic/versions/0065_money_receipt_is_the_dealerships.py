"""The money receipts' and supporting_document's classifier definitions: a
money receipt is the dealership's own.

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-11

payment_receipt / dealer_receipt were "a money receipt for an amount received",
whoever issued it. On the live tenant an insurer's premium receipt for the
customer's own policy (National Insurance, Rs 50,370) was classified
dealer_receipt and counted among the dealership's payments; 5 such receipts,
2 from a defence depot and 1 from another dealership were (product owner
2026-11-11: "payment receipt only in the name of dealership or outlet should
be there").

The money receipts' definition now says the vehicle dealership issues it, and
that an insurer's or any other party's receipt is supporting_document;
supporting_document names the insurer's premium receipt among its examples.
Audit Core also sets such a receipt aside whatever it was classified as.

_DEFINITIONS is a snapshot (a migration must not import app code);
tests/test_document_type_definitions.py pins it, over the earlier ones, to
GLOBAL_DOCUMENT_TYPE_DEFINITIONS. Nothing is re-classified here. Forward-only,
like 0058/0059/0060/0062/0064.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_MONEY_RECEIPT = (
    'A money receipt the vehicle dealership issues for an amount it received: receipt number, '
    'date, the amount in figures and in words, and the mode of payment. Not an insurance '
    "company's premium receipt or any other party's receipt (supporting_document), and not a "
    'vehicle delivery acknowledgement such as a New Vehicle Delivery Receipt, which records '
    'the vehicle handed over and no amount.'
)

_DEFINITIONS: dict[str, str] = {
    "payment_receipt": _MONEY_RECEIPT,
    "dealer_receipt": _MONEY_RECEIPT,
    "supporting_document": (
        'Any page that is none of the other candidates, e.g. an email or approval note printout, '
        "a Transaction Regularization Form, a covering letter or an insurer's premium receipt. A "
        'Form 21 (Sale Certificate, "See Rule 47") is form_21 and a New Vehicle Delivery Receipt '
        '(vehicle handed over, no amount) is delivery_receipt when those are candidates; '
        'otherwise they are supporting_document.'
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for key, definition in _DEFINITIONS.items():
        conn.execute(
            sa.text(
                "UPDATE docintel.document_types SET description=:d, updated_at_utc=now() "
                "WHERE owner_tenant_id IS NULL AND document_type_key=:k "
                "AND description IS DISTINCT FROM :d"
            ),
            {"k": key, "d": definition},
        )


def downgrade() -> None:
    # Forward-only, as 0058/0059/0060/0062/0064.
    pass

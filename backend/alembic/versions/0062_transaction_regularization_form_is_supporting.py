"""cost_sheet's and supporting_document's classifier definitions: the
Transaction Regularization Form.

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-05

The dealers' Transaction Regularization Form -- their internal margin and
discount sanction (purchase price, holding cost, manufacturer support, sale
price, discount offered, net profit; the approved scheme, cash discount and
extras written in by hand) -- was classified cost_sheet on the live tenant
(27 pages, Aditya and Utkal), and so were Utkal's discount approval sheets
("Approval Sheet", "Vehicle Extra Discount Approval Form", 20 pages). They
print no on-road price and no payments; the product owner (2026-11-05) keeps
them as supporting (additional) documents, never read for figures. cost_sheet's definition now says so, and supporting_document's names it.

_DEFINITIONS is a snapshot (a migration must not import app code);
tests/test_document_type_definitions.py pins it, over 0058's, 0059's and
0060's, to GLOBAL_DOCUMENT_TYPE_DEFINITIONS. Nothing is re-classified here.
Forward-only, like 0058/0059/0060.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

_DEFINITIONS: dict[str, str] = {
    'cost_sheet': (
        "A dealer's price sheet for one vehicle: ex-showroom, RTO, insurance, accessories and "
        'discounts up to an on-road total. When customer_ledger is also a candidate, cost_sheet '
        'is only a bare price quotation with no payments; a deal sheet listing charges, discounts '
        'and payments received is customer_ledger, whatever its title. A Transaction '
        'Regularization Form or a discount approval sheet (internal discount sanction) is '
        'supporting_document.'
    ),
    'supporting_document': (
        'Any page that is none of the other candidates, e.g. an email or approval note printout, '
        'a Transaction Regularization Form or a covering letter. A Form 21 (Sale Certificate, '
        '"See Rule 47") is form_21 and a New Vehicle Delivery Receipt (vehicle handed over, no '
        'amount) is delivery_receipt when those are candidates; otherwise they are '
        'supporting_document.'
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
    # Forward-only, as 0058/0059/0060.
    pass

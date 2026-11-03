"""booking_form's classifier definition: not the Offer Letter / Payment Details sheet.

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-03

On the live tenant every Shivnath "Offer Letter / Payment Details" sheet -- the
dealer's priced deal sheet (its NDC): a numbered grid of charges up to the
Onroad Price, the deductions, the Finance Amount, the Final Payment and a table
of cash receipts -- was classified booking_form, because it also prints a
booking amount. customer_ledger's definition (0058) already names the sheet;
booking_form's now says it is not one.

_DEFINITIONS is a snapshot (a migration must not import app code);
tests/test_document_type_definitions.py pins it, over 0058's and 0059's, to
GLOBAL_DOCUMENT_TYPE_DEFINITIONS. Nothing is re-classified here. Forward-only,
like 0058/0059.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

_DEFINITIONS: dict[str, str] = {
    'booking_form': (
        "The dealer's vehicle booking (order) form filled in at booking: booking number and date, "
        "customer details, model, variant and colour, price build-up, booking amount paid, expected "
        "delivery. Not an Offer Letter / Payment Details sheet (charges up to Onroad Price, Finance "
        "Amount, Final Payment, cash receipts table), which is customer_ledger."
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
    # Forward-only, as 0058/0059.
    pass

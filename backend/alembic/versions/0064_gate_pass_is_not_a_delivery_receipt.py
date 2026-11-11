"""gate_pass's and delivery_receipt's classifier definitions: a page titled
Gate Pass is the gate pass.

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-11

Since delivery_receipt became a candidate (0059, 2026-11-02) the live tenant's
Utkal gate pass -- "UTKAL AUTOMOBILES LIMITED, GATE PASS": serial number, date,
name, address, model, chassis number, a tools and accessories checklist and the
customer's signature under "Received the above mentioned vehicle in good
condition" -- was classified delivery_receipt on 64 of 156 pages (3 to 11 Nov;
none at Aditya or Shivnath). gate_pass's definition said only "the gate pass or
delivery date and the car number", while delivery_receipt's described exactly
what the form prints. Audit Core takes the delivery date, and counts the day's
deliveries against the gate register, from the gate pass alone, so those
deliveries had no delivery date (product owner 2026-11-11: "PC is uploading
gate pass and it is being recognized as different document").

gate_pass's definition now describes the form and says a page titled Gate Pass
is gate_pass; delivery_receipt's says the same from its side.

_DEFINITIONS is a snapshot (a migration must not import app code);
tests/test_document_type_definitions.py pins it, over the earlier ones, to
GLOBAL_DOCUMENT_TYPE_DEFINITIONS. Nothing is re-classified here. Forward-only,
like 0058/0059/0060/0062.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

_DEFINITIONS: dict[str, str] = {
    "gate_pass": (
        "The dealer's gate pass letting the vehicle out on delivery, titled Gate Pass: serial "
        'number, date and time, customer name and address, model, chassis and engine numbers, '
        'often a tools and accessories checklist the customer signs for the vehicle received. A '
        'page titled Gate Pass is gate_pass, never delivery_receipt.'
    ),
    "delivery_receipt": (
        "The customer's acknowledgement of taking delivery of the new vehicle, titled e.g. New "
        "Vehicle Delivery Receipt or Delivery Note: its number, delivery date, customer, model, "
        "chassis and engine numbers, any financier. It has no amount: not a money receipt, not the "
        "dealer's delivery order (DO) cover sheet. A page titled Gate Pass is the gate pass "
        "(gate_pass), also when the customer signs it."
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
    # Forward-only, as 0058/0059/0060/0062.
    pass

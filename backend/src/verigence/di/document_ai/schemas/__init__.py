"""document_ai/schemas/__init__.py — Document Schema Registry.

Central registry: maps document_type_key → SchemaDefinition.

D20: Adding a new document type requires:
  1. Create document_ai/schemas/<new_type_key>.py with a SchemaDefinition
  2. Import and register it here in SCHEMA_REGISTRY
  3. Add a seed row to document_types in the next migration
  No other code changes required.

Every key in SCHEMA_REGISTRY must correspond to an existing row in
docintel.document_types (global seed or tenant-owned).
"""
from __future__ import annotations

from verigence.di.document_ai.schemas._fallback import FALLBACK_SCHEMA
from verigence.di.document_ai.schemas.bank_statement import BANK_STATEMENT_SCHEMA
from verigence.di.document_ai.schemas.base import SchemaDefinition
from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA
from verigence.di.document_ai.schemas.dealer_receipt import DEALER_RECEIPT_SCHEMA
from verigence.di.document_ai.schemas.delivery_order import DELIVERY_ORDER_SCHEMA
from verigence.di.document_ai.schemas.insurance_cover import INSURANCE_COVER_SCHEMA
from verigence.di.document_ai.schemas.pan_card import PAN_CARD_SCHEMA
from verigence.di.document_ai.schemas.upi_screenshot import UPI_SCREENSHOT_SCHEMA
from verigence.di.document_ai.schemas.upi_transaction import UPI_TRANSACTION_SCHEMA

__all__ = [
    "SCHEMA_REGISTRY",
    "FALLBACK_SCHEMA",
    "SchemaDefinition",
    "get_schema",
]

# ── Registry ──────────────────────────────────────────────────────────────────
# Keys must match document_types.document_type_key in the DB exactly.
# Display names must match document_types.display_name.
#
# Existing types (seeded migration 0005 — insurance_cover already in DB):
#   insurance_cover → Insurance Cover Note
#
# New types (seeded migration 0007):
#   booking_form           → Booking Form
#   dealer_receipt         → Dealer Receipt
#   bank_statement_extract → Bank Statement Extract
#   upi_transaction        → UPI Transaction
#   delivery_order_cover   → Delivery Order Cover
#   upi_screenshot         → UPI Screenshot

SCHEMA_REGISTRY: dict[str, SchemaDefinition] = {
    # ── Dealer audit domain (new — migration 0007) ───────────────────────────
    "booking_form":           BOOKING_FORM_SCHEMA,
    "dealer_receipt":         DEALER_RECEIPT_SCHEMA,
    "bank_statement_extract": BANK_STATEMENT_SCHEMA,
    "upi_transaction":        UPI_TRANSACTION_SCHEMA,
    "delivery_order_cover":   DELIVERY_ORDER_SCHEMA,
    "upi_screenshot":         UPI_SCREENSHOT_SCHEMA,
    # ── Existing global types with Gemini schemas ────────────────────────────
    "insurance_cover":        INSURANCE_COVER_SCHEMA,
    "pan_card":               PAN_CARD_SCHEMA,
}


def get_schema(document_type_key: str) -> SchemaDefinition:
    """Return the registered SchemaDefinition for document_type_key.

    Returns FALLBACK_SCHEMA when the key is not registered.
    Never raises. Safe to call with any string.
    """
    return SCHEMA_REGISTRY.get(document_type_key, FALLBACK_SCHEMA)
